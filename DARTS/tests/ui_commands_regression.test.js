const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
assert.match(liveMap, /function toggleMapSource\(buttonId, source\)/);
assert.match(liveMap, /function toggleMap\(\)/);
assert.match(liveMap, /addEventListener\('click', toggleMap\)/);
assert.match(liveMap, /toggleMapSource\(buttonId, source\);/);
assert.match(liveMap, /parsedData\.type === 'ui_command'/);

const buttons = {};
const hud = { classes: new Set(), classList: { toggle(name, active) { active ? hud.classes.add(name) : hud.classes.delete(name); } } };
function element(id) {
    if (!buttons[id]) {
        buttons[id] = {
            style: {}, className: '', innerText: '', active: false,
            addEventListener(type, listener) { this[type] = listener; },
            classList: { toggle(name, active) { buttons[id].active = active; } },
        };
    }
    return buttons[id];
}
const aircraft = [{ icao: 'ABC123' }];
const context = {
    document: {
        getElementById: element,
        querySelector: () => hud,
        documentElement: { style: { setProperty() {} } },
    },
    window: { innerWidth: 1000, innerHeight: 800 },
    hiddenMapSources: { ifr_waypoints: false, vfr_waypoints: false },
    L: { map: () => ({
        setView() { return this; }, invalidateSize() {},
        getCenter: () => ({ lat: 0, lng: 0 }), getZoom: () => 10,
    }) },
    REF_LAT: 0, REF_LON: 0, COS_LAT: 1,
    mapContainer: element('map-container'), rCanvas: element('radar'),
    setTimeout: (callback) => callback(),
    ws: {}, WebSocket: { OPEN: 1 },
    perfCounters: { lastWsTime: 0 },
    lastAircraftList: aircraft,
    trailMin: element('trail-min'), trailMax: element('trail-max'),
    trailVal: element('trail-val'), trailStartCode: element('trail-start-code'), trailEndCode: element('trail-end-code'),
    TRAIL_WINDOW_MAX_MINUTES: 1440, MIN_TRAIL_SPAN_MINUTES: 0.1,
    HTTP_API: 'http://localhost:8766',
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    updateSliderLabels() {
        let min = Number(context.trailMin.value), max = Number(context.trailMax.value);
        if (min > max - context.MIN_TRAIL_SPAN_MINUTES) min = max - context.MIN_TRAIL_SPAN_MINUTES;
        context.trailMin.value = min.toFixed(1);
        context.trailMax.value = max.toFixed(1);
    },
    clampTrailRange() { context.updateSliderLabels(); },
    console: { info() {}, warn() {}, log() {}, error() {} },
};
context.trailMin.value = '0';
context.trailMax.value = '1440';
const toggleStart = liveMap.indexOf('        // --- Element Toggle');
const toggleEnd = liveMap.indexOf('        const tileLayerFactories', toggleStart);
assert.ok(toggleStart >= 0 && toggleEnd > toggleStart);
vm.runInNewContext(liveMap.slice(toggleStart, toggleEnd), context);

const messageStart = liveMap.indexOf('        ws.onmessage = (event) => {');
const messageEnd = liveMap.indexOf('        hydrateTrailHistory();', messageStart);
assert.ok(messageStart >= 0 && messageEnd > messageStart);
vm.runInNewContext(liveMap.slice(messageStart, messageEnd), context);
const reports = [];
context.ws.readyState = 1;
context.ws.send = (message) => reports.push(JSON.parse(message));
function remote(command) {
    context.ws.onmessage({ data: JSON.stringify({ type: 'ui_command', command }) });
    assert.strictEqual(context.lastAircraftList, aircraft, 'control must not replace aircraft state');
}

for (const [command, buttonId, source] of [
    ['toggle_ifr', 'btn-ifr-toggle', 'ifr_waypoints'],
    ['toggle_vfr', 'btn-vfr-toggle', 'vfr_waypoints'],
]) {
    remote(command);
    assert.strictEqual(context.hiddenMapSources[source], true);
    assert.strictEqual(element(buttonId).active, true);
    element(buttonId).click();
    assert.strictEqual(context.hiddenMapSources[source], false);
    assert.strictEqual(element(buttonId).active, false);
    remote(command);
    remote(command);
    assert.strictEqual(context.hiddenMapSources[source], false);
    assert.strictEqual(element(buttonId).active, false);
}

remote('toggle_map');
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle active');
assert.strictEqual(element('btn-network').innerText, 'MAP TOGGLE');
assert.strictEqual(context.mapContainer.style.display, 'block');
assert.strictEqual(element('map-style-dropdown').style.visibility, 'visible');
assert.strictEqual(element('map-style-dropdown').disabled, false);
element('btn-network').click();
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');
assert.strictEqual(context.mapContainer.style.display, 'none');
assert.strictEqual(element('map-style-dropdown').style.visibility, 'hidden');
assert.strictEqual(element('map-style-dropdown').disabled, true);
remote('toggle_map');
remote('toggle_map');
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');

for (const [command, span, min] of [
    ['span_30m', '30m', 1410], ['span_1h', '1h', 1380], ['span_2h', '2h', 1320],
    ['span_4h', '4h', 1200], ['span_day', 'day', 0],
]) {
    remote(command);
    assert.strictEqual(context.trailMin.value, `${min}.0`);
    assert.strictEqual(context.trailMax.value, '1440.0');
    assert.strictEqual(reports.at(-1).state.activeSpan, span);
    for (const candidate of ['30m', '1h', '2h', '4h', 'day']) {
        assert.strictEqual(candidate === reports.at(-1).state.activeSpan, candidate === span, 'exactly one span selected');
    }
}

const sliderStart = liveMap.indexOf("        trailMin.addEventListener('input'");
const sliderEnd = liveMap.indexOf('        function applyTimecodeInput', sliderStart);
vm.runInNewContext(liveMap.slice(sliderStart, sliderEnd), context);
context.trailMin.input();
assert.strictEqual(reports.at(-1).state.activeSpan, null, 'manual slider input deselects the span radio group');

remote('span_1h');
remote('toggle_night');
assert.deepStrictEqual([context.trailMin.value, context.trailMax.value], ['1410.0', '1440.0']);
assert.strictEqual(reports.at(-1).state.nightMode, true);
assert.strictEqual(reports.at(-1).state.osdVisible, false);
remote('toggle_night');
assert.deepStrictEqual([context.trailMin.value, context.trailMax.value], ['1380.0', '1440.0']);
assert.strictEqual(reports.at(-1).state.activeSpan, '1h');
assert.strictEqual(reports.at(-1).state.nightMode, false);
assert.strictEqual(reports.at(-1).state.osdVisible, true);
remote('toggle_osd');
assert.strictEqual(reports.at(-1).state.osdVisible, false);
assert.ok(hud.classes.has('osd-hidden'));
remote('toggle_osd');
assert.strictEqual(reports.at(-1).state.osdVisible, true);
assert.ok(!hud.classes.has('osd-hidden'));
remote('unknown');
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');

class KeyboardTarget {
    constructor(tagName = 'DIV', parent = null, isContentEditable = false) {
        Object.assign(this, { tagName, parent, isContentEditable });
    }
    closest(selector) {
        assert.strictEqual(selector, 'input, textarea, select');
        return ['INPUT', 'TEXTAREA', 'SELECT'].includes(this.tagName) ? this : this.parent?.closest(selector);
    }
}
context.Element = KeyboardTarget;
context.measureActive = false;
let keydown;
context.document.addEventListener = (type, listener) => {
    assert.strictEqual(type, 'keydown');
    keydown = listener;
};
const keyboardStart = liveMap.indexOf("        document.addEventListener('keydown', (e) => {");
const keyboardEnd = liveMap.indexOf('        function openTagConfig()', keyboardStart);
assert.ok(keyboardStart >= 0 && keyboardEnd > keyboardStart);
vm.runInNewContext(liveMap.slice(keyboardStart, keyboardEnd), context);
function press(key, overrides = {}) {
    const event = {
        key, target: new KeyboardTarget(), defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; },
        ...overrides,
    };
    keydown(event);
    return event;
}
for (const key of ['m', 'M', 'n', 'N']) {
    for (const overrides of [
        { repeat: true }, { ctrlKey: true }, { altKey: true }, { metaKey: true },
        { defaultPrevented: true }, { isComposing: true },
        ...['INPUT', 'TEXTAREA', 'SELECT'].map(tag => ({ target: new KeyboardTarget(tag) })),
        { target: new KeyboardTarget('OPTION', new KeyboardTarget('SELECT')) },
        { target: new KeyboardTarget('DIV', null, true) },
        { target: new KeyboardTarget('SPAN', null, true) },
    ]) {
        const count = reports.length;
        const event = press(key, overrides);
        assert.strictEqual(reports.length, count, `${key} must ignore ${JSON.stringify(overrides)}`);
        assert.strictEqual(event.defaultPrevented, !!overrides.defaultPrevented, 'ignored shortcuts keep their default behavior');
    }
}
assert.strictEqual(press('m').defaultPrevented, true);
assert.strictEqual(reports.at(-1).state.osdVisible, false);
assert.ok(hud.classes.has('osd-hidden'));
assert.strictEqual(press('M', { shiftKey: true }).defaultPrevented, true);
assert.strictEqual(reports.at(-1).state.osdVisible, true);
assert.ok(!hud.classes.has('osd-hidden'));
assert.strictEqual(press('n').defaultPrevented, true);
assert.strictEqual(reports.at(-1).state.nightMode, true);
assert.strictEqual(reports.at(-1).state.osdVisible, false);
assert.strictEqual(reports.at(-1).state.activeSpan, '30m');
assert.strictEqual(press('N', { shiftKey: true }).defaultPrevented, true);
assert.strictEqual(reports.at(-1).state.nightMode, false);
assert.strictEqual(reports.at(-1).state.osdVisible, true);
assert.strictEqual(reports.at(-1).state.activeSpan, '1h');
assert.deepStrictEqual([context.trailMin.value, context.trailMax.value], ['1380.0', '1440.0']);
const reportCount = reports.length;
assert.strictEqual(press('x').defaultPrevented, false);
assert.strictEqual(reports.length, reportCount);
context.measureActive = true;
context.measureEnd = {};
context.measureEndEntityId = 'ABC123';
let measureCancelled = false;
context.cancelMeasure = () => { measureCancelled = true; };
assert.strictEqual(press('Escape', { repeat: true, ctrlKey: true }).defaultPrevented, false);
assert.strictEqual(context.measureEnd, null);
assert.strictEqual(context.measureEndEntityId, null);
press('Escape');
assert.strictEqual(measureCancelled, true);
assert.strictEqual(reports.length, reportCount, 'Escape must not toggle UI state');

// The map reports its authoritative MAP/IFR/VFR state (and echoes request IDs).
reports.length = 0;
context.ws.onmessage({ data: JSON.stringify({ type: 'ui_command', command: 'toggle_ifr', request_id: 'sd-42' }) });
assert.deepStrictEqual(reports.pop(), {
    action: 'ui_state', request_id: 'sd-42',
    state: {
        mapEnabled: false, ifrEnabled: false, vfrEnabled: true,
        activeSpan: '1h', nightMode: false, osdVisible: true, exportState: 'idle', exportProgress: null,
    },
});
element('btn-network').click();
assert.deepStrictEqual(reports.pop().state, {
    mapEnabled: true, ifrEnabled: false, vfrEnabled: true,
    activeSpan: '1h', nightMode: false, osdVisible: true, exportState: 'idle', exportProgress: null,
});
element('btn-vfr-toggle').click();
assert.deepStrictEqual(reports.pop().state, {
    mapEnabled: true, ifrEnabled: false, vfrEnabled: false,
    activeSpan: '1h', nightMode: false, osdVisible: true, exportState: 'idle', exportProgress: null,
});
remote('toggle_map');
assert.deepStrictEqual(reports.pop(), {
    action: 'ui_state', request_id: null,
    state: {
        mapEnabled: false, ifrEnabled: false, vfrEnabled: false,
        activeSpan: '1h', nightMode: false, osdVisible: true, exportState: 'idle', exportProgress: null,
    },
});
context.ws.readyState = 3;
element('btn-ifr-toggle').click();
assert.strictEqual(reports.length, 0, 'closed sockets must not be written');

const liveGrid = fs.readFileSync(path.join(__dirname, '..', 'live_grid.html'), 'utf8');
const gridStart = liveGrid.indexOf('    ws.onmessage = (event) => {');
const gridEnd = liveGrid.indexOf('\n    };', gridStart) + '\n    };'.length;
assert.ok(gridStart >= 0 && gridEnd > gridStart);
const gridUpdates = [];
const gridContext = {
    ws: {}, console, ledgerCountVal: { innerText: '42' },
    updateTable: (airframes) => gridUpdates.push(airframes),
};
vm.runInNewContext(liveGrid.slice(gridStart, gridEnd), gridContext);
for (const command of ['toggle_map', 'toggle_ifr', 'toggle_vfr', 'span_30m', 'span_1h', 'span_2h', 'span_4h', 'span_day', 'toggle_night', 'toggle_osd', 'export_3d']) {
    gridContext.ws.onmessage({ data: JSON.stringify({ type: 'ui_command', command }) });
}
assert.strictEqual(gridUpdates.length, 0, 'UI commands must not clear grid rows');
assert.strictEqual(gridContext.ledgerCountVal.innerText, '42');
gridContext.ws.onmessage({ data: JSON.stringify({ airframes: aircraft }) });
assert.strictEqual(gridUpdates.length, 1);
assert.strictEqual(gridUpdates[0][0].icao, 'ABC123');

async function testExportAction() {
    const timers = [];
    const alerts = [];
    context.ws.readyState = 1;
    context.setTimeout = (callback, delay) => timers.push({ callback, delay });
    context.alert = (message) => alerts.push(message);
    let finishExport;
    context.exportTrail3DGeoJSON = () => new Promise((resolve) => { finishExport = resolve; });
    const actionStart = liveMap.indexOf('        async function startExport3D()');
    const actionEnd = liveMap.indexOf("        document.getElementById('btn-export-geojson-3d')", actionStart);
    vm.runInNewContext(liveMap.slice(actionStart, actionEnd), context);
    reports.length = 0;
    remote('export_3d');
    await Promise.resolve();
    await context.startExport3D();
    assert.deepStrictEqual(reports.map((report) => report.state.exportState), ['working'], 'busy export press is ignored');
    finishExport();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepStrictEqual(reports.map((report) => report.state.exportState), ['working', 'done']);
    assert.strictEqual(reports.at(-1).state.exportProgress, 100);
    assert.strictEqual(timers[0].delay, 800);
    timers.shift().callback();
    assert.strictEqual(reports.at(-1).state.exportState, 'idle');
    context.exportTrail3DGeoJSON = async () => { throw new Error('export failed'); };
    timers.length = 0;
    await context.startExport3D();
    assert.deepStrictEqual(reports.slice(-2).map((report) => report.state.exportState), ['working', 'error']);
    assert.strictEqual(timers[0].delay, 1500);
    assert.strictEqual(alerts.length, 1);
    console.log('ui_commands_regression: OK');
}
testExportAction().catch((error) => { console.error(error); process.exitCode = 1; });
