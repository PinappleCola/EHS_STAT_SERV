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
    document: { getElementById: element },
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
    console,
};
const toggleStart = liveMap.indexOf('        // --- Element Toggle');
const toggleEnd = liveMap.indexOf('        const tileLayerFactories', toggleStart);
assert.ok(toggleStart >= 0 && toggleEnd > toggleStart);
vm.runInNewContext(liveMap.slice(toggleStart, toggleEnd), context);

const messageStart = liveMap.indexOf('        ws.onmessage = (event) => {');
const messageEnd = liveMap.indexOf('        hydrateTrailHistory();', messageStart);
assert.ok(messageStart >= 0 && messageEnd > messageStart);
vm.runInNewContext(liveMap.slice(messageStart, messageEnd), context);
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
assert.strictEqual(element('map-style-dropdown').style.display, 'block');
element('btn-network').click();
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');
assert.strictEqual(context.mapContainer.style.display, 'none');
assert.strictEqual(element('map-style-dropdown').style.display, 'none');
remote('toggle_map');
remote('toggle_map');
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');
remote('unknown');
assert.strictEqual(element('btn-network').className, 'btn-action btn-toggle');

console.log('ui_commands_regression: OK');
