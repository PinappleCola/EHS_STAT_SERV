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
const rendered = vm.runInContext('formatVdl2Frame(sample)', context);
assert.match(rendered, /^\[2026-11-06 04:04:26 GMT\] \[136\.975\] \[-2\.9\/-27\.0 dBFS\] \[24\.1 dB\] \[-1\.4 ppm\]/);
assert.match(rendered, /7C7A48 \(Aircraft, Airborne\) -> 10AD4A \(Ground station\): Command/);
assert.match(rendered, /AVLC type: I sseq: 1 rseq: 2 poll: 0/);
assert.match(rendered, / ACARS:\n  Reg: \.VH-YFU Flight: VA0328/);
assert.match(rendered, /Mode: 2 Label: SA Blk id: 0 More: 0 Ack: ! Msg num: M27A/);
assert.match(rendered, /0E20410452S/);

context.sample.vdl2.avlc.acars.msg_text = 'A'.repeat(500) + '\r\n  Second line\n\rThird line';
const fullText = vm.runInContext('formatVdl2Frame(sample)', context);
assert.ok(fullText.includes('A'.repeat(500)), 'long payloads must not be truncated');
assert.ok(fullText.includes('\n     Second line\n   Third line'), 'line breaks and indentation must be preserved');
assert.ok(!fullText.includes('\r'));

context.sample.vdl2.avlc = {
    src: { addr: '7CF836', type: 'Aircraft', status: 'Airborne' },
    dst: { addr: '29E498', type: 'Ground station' },
    frame_type: 'U', cmd: 'XID', pf: true,
    xid: {
        type_descr: 'Link Establishment',
        pub_params: [{ name: 'param_set_id', value: '8885:1993' }],
        vdl_params: [
            { name: 'dst_airport', value: 'YAMB' },
            { name: 'ac_location', value: { loc: { lat: -33.6, lon: 150.9 }, alt: 4000 } },
        ],
    },
};
const xidText = vm.runInContext('formatVdl2Frame(sample)', context);
assert.match(xidText, /AVLC type: U \(XID\) P\/F: 1/);
assert.match(xidText, / XID: Link Establishment\n  Public params:/);
assert.match(xidText, /Destination airport: YAMB/);
assert.match(xidText, /Aircraft location: -33\.6, 150\.9 \| 4000 ft/);

vm.runInContext('latestVdl2Frames = [sample]', context);
context.lastAircraftList = [{ icao: '7cf836', data_tag_inactive: false }];
vm.runInContext('renderVdl2Frames()', context);
let highlights = element('vdl2-frame-output').children.filter(child => child.className === 'vdl2-active-icao');
assert.strictEqual(highlights.length, 1);
assert.strictEqual(highlights[0].textContent, '7CF836');
assert.strictEqual(element('vdl2-frame-output').textContent, xidText);
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
assert.strictEqual(drawCalls.length, 2);
assert.strictEqual(drawCalls[1][1], '7C7A49');
vm.runInContext('drawVdl2Positions(drawing, 0, 0, 1, 1600000)', context);
assert.strictEqual(drawCalls.length, 2, 'positions expire at exactly ten minutes');
element('btn-vdl2-toggle').click();
assert.strictEqual(element('vdl2-console').style.display, 'none');
vm.runInContext('drawVdl2Positions(drawing, 0, 0, 1, 1000000)', context);
assert.strictEqual(drawCalls.length, 2, 'hidden layer must not draw positions');

console.log('vdl2_console_regression: OK');
