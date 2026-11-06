const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
const scriptStart = liveMap.indexOf('    <script>');
const scriptEnd = liveMap.indexOf('</script>', scriptStart);
assert.ok(scriptStart >= 0 && scriptEnd > scriptStart);
new vm.Script(liveMap.slice(scriptStart + '    <script>'.length, scriptEnd));

const elements = {};
function element(id) {
    if (!elements[id]) {
        const classes = new Set();
        elements[id] = {
            value: '',
            textContent: '',
            style: { display: 'none' },
            scrollTop: 0,
            scrollHeight: 0,
            addEventListener(type, listener) { this[type] = listener; },
            setAttribute(name, value) { this[name] = value; },
            classList: { toggle(name, active) { active ? classes.add(name) : classes.delete(name); } },
            classes,
            replaceChildren(fragment) {
                this.children = fragment.children;
                this.textContent = this.children.map(child => child.textContent).join('');
            },
        };
    }
    return elements[id];
}

const context = vm.createContext({
    document: {
        getElementById: element,
        createDocumentFragment: () => ({ children: [], appendChild(child) { this.children.push(child); } }),
        createTextNode: text => ({ textContent: text }),
        createElement: () => ({ textContent: '', className: '' }),
    },
    lastAircraftList: [],
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    setInterval() {},
    console,
});
const source = liveMap.slice(
    liveMap.indexOf('        async function loadVdl2Config()'),
    liveMap.indexOf('        // Init on load, then poll status every 500ms'),
);
assert.ok(source.length > 0);
vm.runInContext(source, context);

context.sample = {
    vdl2: {
        t: { sec: 1793937866, usec: 237966 },
        freq: 136975000,
        sig_level: -2.85,
        noise_level: -27.0,
        freq_skew: -1.4,
        avlc: {
            src: { addr: '7C7A48', type: 'Aircraft', status: 'Airborne' },
            dst: { addr: '10AD4A', type: 'Ground station' },
            cr: 'Command',
            frame_type: 'I',
            sseq: 1,
            rseq: 2,
            poll: false,
            acars: {
                reg: '.VH-YFU',
                flight: 'VA0328',
                label: 'SA',
                msg_num: 'M27',
                msg_num_seq: 'A',
                msg_text: '0E20410452S',
                mode: '2',
                blk_id: '0',
                more: false,
                ack: '!',
            },
        },
    },
};
context.sample.vdl2.avlc.acars.msg_text = 'A'.repeat(500) + '\r\n  Second line\n\rThird line';
context.sample.vdl2.avlc.acars.extra_payload = { detail: 'not omitted' };
vm.runInContext('latestVdl2Frames = [sample]', context);
context.lastAircraftList = [{ icao: '7c7a48', data_tag_inactive: false }];
vm.runInContext('renderVdl2Frames()', context);
assert.ok(element('vdl2-frame-output').textContent.includes('"extra_payload"'));
assert.ok(element('vdl2-frame-output').textContent.includes('A'.repeat(500)), 'long payloads must not be truncated');

context.sample.vdl2.avlc = {
    src: { addr: '7CF836', type: 'Aircraft', status: 'Airborne' },
    dst: { addr: '29E498', type: 'Ground station' },
    frame_type: 'U', cmd: 'XID', pf: true,
    xid: {
        type_descr: 'Link Establishment',
        raw_extension: 'all fields are displayed',
        pub_params: [{ name: 'param_set_id', value: '8885:1993' }],
        vdl_params: [
            { name: 'dst_airport', value: 'YAMB' },
            { name: 'ac_location', value: { loc: { lat: -33.6, lon: 150.9 }, alt: 4000 } },
        ],
    },
};

vm.runInContext('latestVdl2Frames = [sample]', context);
context.lastAircraftList = [{ icao: '7cf836', data_tag_inactive: false }];
vm.runInContext('renderVdl2Frames()', context);
let highlights = element('vdl2-frame-output').children.filter(child => child.className === 'vdl2-active-icao');
assert.strictEqual(highlights.length, 1);
assert.strictEqual(highlights[0].textContent, '7CF836');
assert.ok(element('vdl2-frame-output').textContent.includes('"raw_extension": "all fields are displayed"'));
assert.ok(element('vdl2-frame-output').textContent.includes('"ac_location"'));
context.lastAircraftList[0].data_tag_inactive = true;
vm.runInContext('renderVdl2Frames()', context);
assert.ok(!element('vdl2-frame-output').children.some(child => child.className));
context.lastAircraftList = [{ icao: '7CF836', age: 9 }, { icao: '29E498', data_tag_inactive: false }];
vm.runInContext('renderVdl2Frames()', context);
assert.strictEqual(element('vdl2-frame-output').children.filter(child => child.className).length, 1, 'ground stations must not highlight');
context.lastAircraftList = [{ icao: '7CF836', age: 10 }];
vm.runInContext('renderVdl2Frames()', context);
assert.ok(!element('vdl2-frame-output').children.some(child => child.className));
context.sample.vdl2.avlc.dst = { addr: '7CF836', type: 'Aircraft' };
context.sample.vdl2.avlc.src = { addr: '29E498', type: 'Ground station' };
context.lastAircraftList = [{ icao: '7CF836', data_tag_inactive: false }];
vm.runInContext('renderVdl2Frames()', context);
highlights = element('vdl2-frame-output').children.filter(child => child.className);
assert.strictEqual(highlights.length, 1, 'uplink aircraft destinations must highlight');
assert.strictEqual(highlights[0].textContent, '7CF836');

element('btn-vdl2-toggle').click();
assert.strictEqual(element('vdl2-console').style.display, 'flex');
assert.strictEqual(element('btn-vdl2-toggle')['aria-pressed'], 'true');
context.getCanvasPoint = (lat, lon) => ({ x: lon, y: lat });
const drawCalls = [];
context.drawing = {
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    strokeRect(...args) { drawCalls.push(['envelope', ...args]); },
    fillText(...args) { drawCalls.push(['label', ...args]); },
};
vm.runInContext("vdl2Positions = [{icao: '7C7A49', lat: -32.7, lon: 149.4, report_time: 1000}]; drawVdl2Positions(drawing, 0, 0, 1, 1599000)", context);
assert.strictEqual(drawCalls.length, 3);
assert.strictEqual(drawCalls[1][1], '7C7A49');
assert.strictEqual(drawCalls[2][1], 'VDL2 POS');
assert.strictEqual(drawCalls[2][3] - drawCalls[1][3], 14);
assert.strictEqual(context.drawing.font, "11px 'B612 Mono', Consolas, monospace");
assert.strictEqual(vm.runInContext('findVdl2PositionAt(149.4, -32.7).icao', context), '7C7A49');
vm.runInContext('vdl2PositionLabelScale = 2; drawVdl2Positions(drawing, 0, 0, 1, 1599000)', context);
assert.strictEqual(context.drawing.font, "22px 'B612 Mono', Consolas, monospace");
drawCalls.length = 0;
vm.runInContext('drawVdl2Positions(drawing, 0, 0, 1, 1600000)', context);
assert.strictEqual(drawCalls.length, 0, 'positions expire at exactly ten minutes');

context.positionRecord = {
    vdl2: {
        t: { sec: 1793938360 },
        avlc: {
            src: { addr: '7C7A49', type: 'Aircraft' },
            cr: 'Command',
            frame_type: 'I',
            acars: {
                label: 'H1',
                sublabel: 'M1',
                msg_text: 'POSS32433E149269,SPLIZ,041237,390,',
            },
        },
    },
};
vm.runInContext("position = {icao: '7C7A49', message_type: 'H1/M1 POS', coordinate_text: 'POSS32433E149269', record: positionRecord}; showVdl2Position(position)", context);
assert.ok(element('vdl2-frame-output').textContent.includes('POSS32433E149269,SPLIZ,041237,390,'));
assert.strictEqual(element('vdl2-feed-status').textContent, 'Selected · 7C7A49 · H1/M1 POS');
const coordinateHighlight = element('vdl2-frame-output').children.find(child => child.className === 'vdl2-position-coordinates');
assert.ok(coordinateHighlight);
assert.strictEqual(coordinateHighlight.textContent, 'POSS32433E149269');

vm.runInContext("selectedVdl2Position = null; latestVdl2Frames = [positionRecord]; latestVdl2Coordinates = ['POSS32433E149269']; renderVdl2Frames()", context);
assert.strictEqual(element('vdl2-frame-output').textContent, JSON.stringify(context.positionRecord, null, 2),
    'coordinate highlighting must preserve the entire stream payload');
assert.strictEqual(element('vdl2-frame-output').children.filter(
    child => child.className === 'vdl2-position-coordinates'
).length, 1, 'the stream must highlight validated position coordinates');
vm.runInContext('latestVdl2Coordinates = [null]; renderVdl2Frames()', context);
assert.ok(!element('vdl2-frame-output').children.some(
    child => child.className === 'vdl2-position-coordinates'
), 'coordinate-like text not accepted by the backend must not highlight');

element('btn-vdl2-toggle').click();
assert.strictEqual(element('vdl2-console').style.display, 'none');
vm.runInContext('drawVdl2Positions(drawing, 0, 0, 1, 1000000)', context);
assert.strictEqual(drawCalls.length, 0, 'hidden layer must not draw positions');

console.log('vdl2_console_regression: OK');
