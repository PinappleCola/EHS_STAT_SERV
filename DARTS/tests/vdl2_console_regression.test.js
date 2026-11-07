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
            offsetWidth: 240,
            offsetHeight: 80,
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
        documentElement: { style: { setProperty() {} } },
        getElementById: element,
        createDocumentFragment: () => ({ children: [], appendChild(child) { this.children.push(child); } }),
        createTextNode: text => ({ textContent: text }),
        createElement: () => ({ textContent: '', className: '' }),
    },
    lastAircraftList: [],
    entityCache: {},
    renderHitboxes: [],
    window: { innerWidth: 800, innerHeight: 600 },
    dataTagStyle: { font_family: 'B612 Mono', font_size_px: 11 },
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    setInterval() {},
    console,
});
vm.runInContext(liveMap.slice(
    liveMap.indexOf('        function setDataTagFont('),
    liveMap.indexOf('        function measureDataTag('),
), context);
vm.runInContext(liveMap.slice(
    liveMap.indexOf('        function applyVdl2TextStyle('),
    liveMap.indexOf('        function normalizeDataTagStyle('),
), context);
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
assert.ok(element('vdl2-frame-output').textContent.includes('Reg: .VH-YFU Flight: VA0328'));
assert.ok(element('vdl2-frame-output').textContent.includes('  Message:\n   ' + 'A'.repeat(500)));
assert.ok(element('vdl2-frame-output').textContent.includes('\n     Second line\n   Third line'));
assert.ok(!element('vdl2-frame-output').textContent.includes('"extra_payload"'));
assert.ok(!element('vdl2-frame-output').textContent.startsWith('{'), 'frames use the compact console format');
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
assert.ok(element('vdl2-frame-output').textContent.includes('Destination airport: YAMB'));
assert.ok(element('vdl2-frame-output').textContent.includes('Aircraft location: -33.6, 150.9 | 4000 ft'));
assert.ok(!element('vdl2-frame-output').textContent.includes('"raw_extension"'));
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
    translate(...args) { drawCalls.push(['translate', ...args]); },
    rotate(angle) { drawCalls.push(['rotate', angle]); },
    closePath() {}, fill() {}, arc() {}, setLineDash() {},
    strokeRect(...args) { drawCalls.push(['envelope', ...args]); },
    fillText(...args) { drawCalls.push(['label', ...args]); },
};
vm.runInContext("vdl2Positions = [{icao: '7C7A49', lat: -32.7, lon: 149.4, report_time: 1000}]; drawVdl2Positions(drawing, 0, 0, 1, 1599000)", context);
assert.strictEqual(drawCalls.length, 3);
assert.strictEqual(drawCalls[1][1], '7C7A49');
assert.strictEqual(drawCalls[2][1], 'VDL2 POS');
assert.strictEqual(drawCalls[2][3] - drawCalls[1][3], 14);
assert.strictEqual(context.drawing.font, "11px 'B612 Mono', 'B612 Mono', 'Consolas', monospace");
assert.strictEqual(vm.runInContext('findVdl2PositionAt(149.4, -32.7).icao', context), '7C7A49');
drawCalls.length = 0;
vm.runInContext("vdl2Positions = [{icao: '888168', lat: -33.638077, lon: 150.827522, true_track_deg: 313.417969, message_type: 'ADS-C BASIC', report_time: 1000}]; drawVdl2Positions(drawing, 0, 0, 1, 1599000)", context);
assert.ok(drawCalls.some(call => call[0] === 'rotate' && Math.abs(call[1] - 313.417969 * Math.PI / 180) < 1e-10),
    'ADS-C aircraft silhouette rotates to the reported true track');
assert.ok(drawCalls.some(call => call[0] === 'translate' && call[1] === 150.827522 && call[2] === -33.638077));
assert.ok(drawCalls.some(call => call[0] === 'label' && call[1] === 'ADS-C BASIC'));
vm.runInContext('vdl2PositionLabelScale = 2; drawVdl2Positions(drawing, 0, 0, 1, 1599000)', context);
assert.strictEqual(context.drawing.font, "22px 'B612 Mono', 'B612 Mono', 'Consolas', monospace");
context.dataTagStyle = { font_family: 'Courier New', font_size_px: 16 };
vm.runInContext('vdl2PositionLabelScale = 1; drawVdl2Positions(drawing, 0, 0, 1, 1599000)', context);
assert.strictEqual(context.drawing.font, "16px 'Courier New', 'B612 Mono', 'Consolas', monospace",
    'VDL2 labels use the aircraft data-tag font and size at scale 1');
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
const consoleTextBeforeSelection = element('vdl2-frame-output').textContent;
element('vdl2-feed-status').textContent = 'Watching';
vm.runInContext("position = {icao: '7C7A49', message_type: 'H1/M1 POS', report_time: 1000, coordinate_text: 'POSS32433E149269', record: positionRecord}; vdl2PositionHitboxes = [{x: 149.4, y: 32.7, position}]; showVdl2Position(position)", context);
assert.strictEqual(element('vdl2-frame-output').textContent, consoleTextBeforeSelection);
assert.strictEqual(element('vdl2-feed-status').textContent, 'Watching');
assert.strictEqual(element('vdl2-message-popup').textContent, 'POSS32433E149269,SPLIZ,041237,390,');
assert.strictEqual(element('vdl2-message-popup').style.display, 'block');
assert.strictEqual(element('vdl2-message-popup').style.left, '169.4px');
const coordinateHighlight = element('vdl2-message-popup').children.find(child => child.className === 'vdl2-position-coordinates');
assert.ok(coordinateHighlight);
assert.strictEqual(coordinateHighlight.textContent, 'POSS32433E149269');
vm.runInContext('showVdl2Position({...position})', context);
assert.strictEqual(element('vdl2-message-popup').style.display, 'none', 'clicking the same fix toggles off');
vm.runInContext('showVdl2Position(position); showVdl2Position(null)', context);
assert.strictEqual(element('vdl2-message-popup').style.display, 'none', 'clicking away clears selection');
vm.runInContext('showVdl2Position(position); vdl2PositionHitboxes[0].x = 790; vdl2PositionHitboxes[0].y = 590; updateVdl2MessagePopup()', context);
assert.strictEqual(element('vdl2-message-popup').style.left, '548px', 'popup stays within the viewport');
assert.strictEqual(element('vdl2-message-popup').style.top, '508px');
vm.runInContext('vdl2PositionHitboxes = []; updateVdl2MessagePopup()', context);
assert.strictEqual(element('vdl2-message-popup').style.display, 'none', 'expired fixes dismiss the popup');
const mouseHandlers = {};
Object.assign(context, {
    rCanvas: { addEventListener(name, handler) { mouseHandlers[name] = handler; } },
    isDragging: false, dragStartPos: { x: 149.4, y: 32.7 },
    measureActive: false, hoveredEntity: null, lockedEntity: null, secondaryEntity: null,
    measureStartEntityId: null, measureEndEntityId: null, renderHitboxes: [], entityCache: {},
});
vm.runInContext(liveMap.slice(
    liveMap.indexOf("        rCanvas.addEventListener('mousemove'"),
    liveMap.indexOf("        rCanvas.addEventListener('mouseup'"),
), context);
vm.runInContext(liveMap.slice(
    liveMap.indexOf("        rCanvas.addEventListener('mouseup'"),
    liveMap.indexOf("        rCanvas.addEventListener('mouseleave'"),
), context);
vm.runInContext('vdl2PositionHitboxes = [{x: 149.4, y: 32.7, position}]', context);
mouseHandlers.mouseup({ clientX: 149.4, clientY: 32.7 });
assert.strictEqual(element('vdl2-message-popup').style.display, 'block');
mouseHandlers.mouseup({ clientX: 149.4, clientY: 32.7 });
assert.strictEqual(element('vdl2-message-popup').style.display, 'none');
mouseHandlers.mouseup({ clientX: 149.4, clientY: 32.7 });
context.dragStartPos = { x: 400, y: 300 };
mouseHandlers.mouseup({ clientX: 400, clientY: 300 });
assert.strictEqual(element('vdl2-message-popup').style.display, 'none', 'map background click dismisses the message');
assert.strictEqual(element('vdl2-frame-output').textContent, consoleTextBeforeSelection,
    'real envelope clicks never replace the console stream');

vm.runInContext("vdl2LayerVisible = true; vdl2Positions = [{icao: '888168', lat: -33.638077, lon: 150.827522, true_track_deg: 313.417969, message_type: 'ADS-C BASIC', report_time: 1599}]; renderHitboxes = []; drawVdl2Positions(drawing, 0, 0, 1, 1600000)", context);
const adscId = 'VDL2_ADS-C BASIC_888168_1599_-33.638077_150.827522';
assert.ok(vm.runInContext(`Boolean(entityCache['${adscId}'] && renderHitboxes.some(hit => hit.id === '${adscId}'))`, context),
    'ADS-C markers are registered as measurement hitboxes');
context.isDragging = false;
context.dragStartPos = { x: 150.827522, y: -33.638077 };
mouseHandlers.mousemove({ clientX: 150.827522, clientY: -33.638077 });
assert.strictEqual(context.hoveredEntity, adscId);
mouseHandlers.mouseup({ clientX: 150.827522, clientY: -33.638077, ctrlKey: true });
assert.strictEqual(context.measureActive, true, 'Ctrl-clicking an ADS-C marker starts measurement');
assert.strictEqual(context.measureStartEntityId, adscId);
context.renderHitboxes = [{ id: 'WPT_TEST', x: 180, y: -30 }];
context.entityCache.WPT_TEST = { lat: -30, lon: 180, alt: 'GROUND', _isWaypoint: true };
mouseHandlers.mousemove({ clientX: 180, clientY: -30 });
context.dragStartPos = { x: 180, y: -30 };
mouseHandlers.mouseup({ clientX: 180, clientY: -30, ctrlKey: true });
assert.strictEqual(context.measureEndEntityId, 'WPT_TEST',
    'measurement can run from an ADS-C report to a waypoint');
context.measureActive = false;
context.measureStartEntityId = null;
context.measureEndEntityId = null;
context.renderHitboxes = [{ id: 'WPT_TEST', x: 180, y: -30 }];
mouseHandlers.mousemove({ clientX: 180, clientY: -30 });
context.dragStartPos = { x: 180, y: -30 };
mouseHandlers.mouseup({ clientX: 180, clientY: -30, ctrlKey: true });
mouseHandlers.mousemove({ clientX: 150.827522, clientY: -33.638077 });
context.dragStartPos = { x: 150.827522, y: -33.638077 };
mouseHandlers.mouseup({ clientX: 150.827522, clientY: -33.638077, ctrlKey: true });
assert.strictEqual(context.measureStartEntityId, 'WPT_TEST');
assert.strictEqual(context.measureEndEntityId, adscId,
    'measurement can run from a waypoint to an ADS-C report');

vm.runInContext("selectedVdl2Position = null; latestVdl2Frames = [positionRecord]; latestVdl2Coordinates = ['POSS32433E149269']; renderVdl2Frames()", context);
assert.ok(element('vdl2-frame-output').textContent.includes('7C7A49 (Aircraft) -> ?: Command'));
assert.ok(element('vdl2-frame-output').textContent.includes('  Message:\n   POSS32433E149269,SPLIZ,041237,390,'),
    'coordinate highlighting must preserve the formatted ACARS message');
assert.strictEqual(element('vdl2-frame-output').children.filter(
    child => child.className === 'vdl2-position-coordinates'
).length, 1, 'the stream must highlight validated position coordinates');
vm.runInContext('latestVdl2Coordinates = [null]; renderVdl2Frames()', context);
assert.ok(!element('vdl2-frame-output').children.some(
    child => child.className === 'vdl2-position-coordinates'
), 'coordinate-like text not accepted by the backend must not highlight');

vm.runInContext('showVdl2Position(position)', context);
element('btn-vdl2-toggle').click();
assert.strictEqual(element('vdl2-console').style.display, 'none');
assert.strictEqual(element('vdl2-message-popup').style.display, 'none', 'hiding VDL2 clears its selected message');
drawCalls.length = 0;
vm.runInContext('drawVdl2Positions(drawing, 0, 0, 1, 1000000)', context);
assert.strictEqual(drawCalls.length, 0, 'hidden layer must not draw positions');

(async () => {
    const properties = {};
    context.document.documentElement.style.setProperty = (name, value) => { properties[name] = value; };
    vm.runInContext('vdl2PositionLabelScale = 1; applyVdl2TextStyle()', context);
    assert.strictEqual(properties['--vdl2-console-scale'], '1');
    assert.strictEqual(properties['--vdl2-message-scale'], '1');
    assert.strictEqual(properties['--vdl2-font-size'], '16px');
    assert.strictEqual(properties['--vdl2-font-family'], "'Courier New', 'B612 Mono', 'Consolas', monospace");
    assert.strictEqual(properties['--vdl2-position-data-colour'], '#ffff00');

    context.positionAdsC = {
        icao: '888168', lat: -33.638077, lon: 150.827522, true_track_deg: 313.417969,
    };
    vm.runInContext("latestVdl2Frames = [{vdl2:{t:{sec:1793927332},avlc:{src:{addr:'888168',type:'Aircraft'},acars:{label:'B6',msg_text:'ADS-C decoded'}}}}]; latestVdl2Coordinates = [null]; latestVdl2AdsC = [positionAdsC]; renderVdl2Frames()", context);
    const positionDataSpans = element('vdl2-frame-output').children.filter(
        child => child.className === 'vdl2-position-data'
    );
    assert.strictEqual(positionDataSpans.length, 2, 'ADS-C position and valid true track are colored in the console');
    assert.strictEqual(positionDataSpans[0].textContent, '-33.638077, 150.827522');
    assert.strictEqual(positionDataSpans[1].textContent, '313.4°T');
    assert.ok(element('vdl2-frame-output').textContent.includes('ADS-C Basic Report: Position: -33.638077, 150.827522 | True track: 313.4°T'));

    context.HTTP_API = 'http://localhost:8766';
    context.fetch = async () => ({
        ok: true,
        json: async () => ({
            configured: true, frames: [context.sample, context.positionRecord],
            positions: [context.position], frame_coordinates: [null, 'POSS32433E149269'],
            frame_ads_c: [context.positionAdsC, null],
        }),
    });
    vm.runInContext('vdl2LayerVisible = true; vdl2PositionHitboxes = [{x: 149.4, y: 32.7, position}]; showVdl2Position(position)', context);
    await vm.runInContext('pollVdl2Feed()', context);
    assert.ok(element('vdl2-frame-output').textContent.includes('Destination airport: YAMB'),
        'the console keeps showing other frames while an envelope is selected');
    assert.ok(element('vdl2-frame-output').textContent.includes('  Message:\n   POSS32433E149269'));
    assert.strictEqual(element('vdl2-feed-status').textContent, 'Watching · 2 frames');
    assert.strictEqual(element('vdl2-message-popup').style.display, 'block');
    assert.strictEqual(element('vdl2-message-popup').textContent, 'POSS32433E149269,SPLIZ,041237,390,');
    context.fetch = async () => ({ ok: true, json: async () => ({ configured: false }) });
    await vm.runInContext('pollVdl2Feed()', context);
    assert.strictEqual(element('vdl2-message-popup').style.display, 'none');
    context.dotRecord = {
        vdl2: { avlc: { src: { addr: '7c6dd9', type: 'Aircraft' },
            acars: { label: 'SA', msg_text: 'Ordinary message payload' } } },
    };
    context.dotFeed = {
        path: 'feed.json', stream_id: 'test-stream', frame_ids: [],
        frames: [], frame_positions: [],
    };
    context.lastAircraftList = [
        { icao: '7C6DD9', lat: '-34.1', lon: '150.9', alt: '19801', data_tag_inactive: false },
    ];
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    context.dotFeed.frames = [context.dotRecord];
    context.dotFeed.frame_ids = [1];
    context.dotFeed.frame_positions = [null];
    vm.runInContext('ingestVdl2MessageDots(dotFeed); ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 1,
        'repeated polling must not duplicate message dots');
    assert.strictEqual(vm.runInContext('vdl2MessageDots[0].lat', context), -34.1);
    context.lastAircraftList[0].lat = '-35';
    context.lastAircraftList[0].data_tag_inactive = true;
    vm.runInContext('pruneVdl2MessageDots()', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots[0].lat', context), -34.1,
        'dots stay at their observed ADS-B position, even while a track is inactive');
    context.dotFeed.frames.push(context.dotRecord);
    context.dotFeed.frame_ids.push(2);
    context.dotFeed.frame_positions.push(null);
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 1,
        'inactive matches do not create dots');
    context.lastAircraftList[0].data_tag_inactive = false;
    context.dotFeed.frames.push(context.dotRecord);
    context.dotFeed.frame_ids.push(3);
    context.dotFeed.frame_positions.push({ message_type: 'H1/DF RSI' });
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 1,
        'decoded position reports must not also create ADS-B message dots');
    let altitudeUsed;
    context.resolveAltitudeTrailColour = altitude => { altitudeUsed = altitude; return [20, 100, 200]; };
    context.drawing.arc = (...args) => drawCalls.push(['dot', ...args]);
    vm.runInContext('vdl2LayerVisible = true; vdl2Positions = []; drawVdl2Positions(drawing, 0, 0, 1, Date.now()); showVdl2Position(vdl2MessageDots[0])', context);
    assert.strictEqual(altitudeUsed, '19801');
    assert.strictEqual(context.drawing.fillStyle, 'rgb(20, 100, 200)');
    assert.ok(drawCalls.some(call => call[0] === 'dot' && call[1] === 150.9 && call[2] === -34.1));
    assert.strictEqual(element('vdl2-message-popup').textContent, 'Ordinary message payload');
    vm.runInContext('showVdl2Position(vdl2MessageDots[0])', context);
    assert.strictEqual(element('vdl2-message-popup').style.display, 'none');
    vm.runInContext('showVdl2Position(vdl2MessageDots[0])', context);
    context.lastAircraftList = [];
    vm.runInContext('pruneVdl2MessageDots()', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 0);
    assert.strictEqual(element('vdl2-message-popup').style.display, 'none');
    context.lastAircraftList = [{ icao: '7C6DD9', lat: -35, lon: 151, alt: 20000, age: 1 }];
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 0,
        'reappearing tracks cannot restore consumed messages');
    context.dotFeed.frames.push(context.dotRecord);
    context.dotFeed.frame_ids.push(4);
    context.dotFeed.frame_positions.push(null);
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 1);
    assert.strictEqual(vm.runInContext('vdl2MessageDots[0].lat', context), -35);
    context.dotFeed.stream_id = 'restarted-stream';
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 0,
        'a restarted feed establishes a baseline instead of replaying buffered messages');
    context.dotFeed.frame_ids = [7];
    context.dotFeed.frames = [context.dotRecord];
    context.dotFeed.frame_positions = [null];
    context.dotFeed.new_frames = [5, 6, 7].map(id => ({ id, record: context.dotRecord, position: null }));
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 3,
        'new-frame batches include messages that fell out of the console buffer');
    vm.runInContext('ingestVdl2MessageDots(dotFeed)', context);
    assert.strictEqual(vm.runInContext('vdl2MessageDots.length', context), 3);
    vm.runInContext("vdl2Positions = [{...positionAdsC, message_type: 'H1/DF RSI', report_time: Date.now()/1000}]; vdl2MessageDots = []; drawVdl2Positions(drawing, 0, 0, 1, Date.now())", context);
    assert.ok(drawCalls.some(call => call[0] === 'label' && call[1] === 'H1/DF RSI'));

    context.positionAdsC.message_type = 'H1/DF RSI';
    vm.runInContext('latestVdl2Frames = [dotRecord]; latestVdl2Coordinates = [null]; latestVdl2AdsC = [positionAdsC]; renderVdl2Frames()', context);
    assert.ok(element('vdl2-frame-output').textContent.includes('RSI Report: Position:'));
    assert.strictEqual(element('vdl2-frame-output').children.filter(
        child => child.className === 'vdl2-position-data').length, 2);
    context.waypointReport = {
        icao: '750260', lat: -33.779869, lon: 150.573807,
        true_track_deg: null, message_type: 'ADS-C WPT CHANGE',
        report_time: Date.now() / 1000,
        predicted_route: [
            {label: 'NEXT', lat: -33.746567, lon: 151.124325, eta_sec: 351},
            {label: 'NEXT+1', lat: -33.845959, lon: 151.149902},
        ],
    };
    vm.runInContext('vdl2Positions = [waypointReport]; drawVdl2Positions(drawing, 0, 0, 1, Date.now())', context);
    assert.strictEqual(vm.runInContext('vdl2PositionHitboxes.length', context), 3);
    assert.ok(drawCalls.some(call => call[0] === 'label' && call[1] === '750260 NEXT'));
    assert.ok(drawCalls.some(call => call[0] === 'label' && call[1] === '750260 NEXT+1'));
    vm.runInContext('showVdl2Position(vdl2PositionHitboxes[1].position)', context);
    assert.ok(element('vdl2-message-popup').textContent.includes('Not an observed aircraft position.'));
    assert.ok(element('vdl2-message-popup').textContent.includes('ETA from report: 351 s'));
    vm.runInContext('showVdl2Position(vdl2PositionHitboxes[1].position)', context);
    assert.strictEqual(element('vdl2-message-popup').style.display, 'none');
    vm.runInContext('latestVdl2AdsC = [waypointReport]; renderVdl2Frames()', context);
    assert.ok(element('vdl2-frame-output').textContent.includes('ADS-C Waypoint Change: Position:'));
    assert.ok(element('vdl2-frame-output').textContent.includes('Predicted NEXT+1:'));
    console.log('vdl2_console_regression: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
