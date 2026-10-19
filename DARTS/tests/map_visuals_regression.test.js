const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
for (const [, script] of liveMap.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    new vm.Script(script);
}
const css = liveMap.match(/<style>([\s\S]*?)<\/style>/)[1];
const visualRules = [...css.matchAll(/([^{}]+)\{([^{}]*--(?:map-mono-filter|map-brightness-user|night-map-brightness)[^{}]*)\}/g)];
assert.strictEqual(visualRules.length, 1, 'visual filters must have a single tile-only target');
assert.strictEqual(visualRules[0][1].trim(), '.leaflet-tile-pane');
assert.match(visualRules[0][2], /var\(--map-mono-filter, brightness\(1\)\) brightness\(calc\(var\(--map-brightness-user, 1\) \* var\(--night-map-brightness, 1\)\)\)/);
assert.match(liveMap, /<filter id="map-mono-filter" color-interpolation-filters="sRGB">/);
assert.match(liveMap, /for="map-brightness"/);
assert.match(liveMap, /id="map-brightness" type="range" min="0" max="200" step="1" value="100"/);
assert.match(liveMap, /id="btn-mono-map"[^>]*type="button" aria-pressed="false"/);
assert.match(liveMap, /for="map-mono-color"/);
assert.match(liveMap, /id="map-mono-color"[^>]*type="color" value="#ffffff"/);

const elements = {};
function element(id) {
    if (!elements[id]) {
        const classes = new Set();
        elements[id] = {
            value: '', style: {}, attributes: {}, classes,
            addEventListener(type, listener) { this[type] = listener; },
            setAttribute(name, value) { this.attributes[name] = value; },
            classList: { toggle(name, active) { active ? classes.add(name) : classes.delete(name); } },
        };
    }
    return elements[id];
}
element('map-brightness').value = '100';
element('map-mono-color').value = '#ffffff';
element('map-style-dropdown').value = 'carto-dark';
const properties = {};
const layers = new Set();
const map = {
    setView() { return this; }, invalidateSize() {},
    getCenter: () => ({ lat: 0, lng: 0 }), getZoom: () => 10,
    hasLayer: layer => layers.has(layer), removeLayer: layer => layers.delete(layer),
};
let resolveConfig;
const context = vm.createContext({
    document: {
        getElementById: element,
        querySelector: () => element('hud'),
        documentElement: { style: { setProperty(name, value) { properties[name] = String(value); } } },
    },
    L: {
        map: () => map,
        tileLayer: (url, options) => ({
            url, options, addTo() { layers.add(this); }, bringToFront() {},
        }),
    },
    window: { innerWidth: 1000, innerHeight: 800 },
    REF_LAT: 0, REF_LON: 0, COS_LAT: 1,
    mapContainer: element('map-container'), rCanvas: element('radar-canvas'),
    trailMin: element('trail-min'), trailMax: element('trail-max'),
    TRAIL_WINDOW_MAX_MINUTES: 1440,
    ws: null, WebSocket: { OPEN: 1 },
    setTimeout: callback => callback(),
    updateSliderLabels() {}, clampTrailRange() {},
    HTTP_API: 'http://localhost:8766',
    fetch: () => new Promise(resolve => { resolveConfig = resolve; }),
    console,
});
function runSection(startMarker, endMarker) {
    const start = liveMap.indexOf(startMarker);
    const end = liveMap.indexOf(endMarker, start);
    assert.ok(start >= 0 && end > start);
    vm.runInContext(liveMap.slice(start, end), context);
}
runSection('        // --- Map-only visual controls', '        // --- Element Toggle');
runSection('        // --- Viewport State Engine', "        rCanvas.addEventListener('mousedown'");
const state = () => JSON.parse(vm.runInContext('JSON.stringify(mapVisualState)', context));
const matrix = () => element('map-mono-matrix').attributes.values.split(' ').map(Number);
function input(id, value) {
    element(id).value = value;
    element(id).input();
}
function assertTint(hex) {
    input('map-mono-color', hex);
    const values = matrix();
    assert.strictEqual(values.length, 20);
    for (let channel = 0; channel < 3; channel++) {
        const tint = parseInt(hex.slice(1 + channel * 2, 3 + channel * 2), 16) / 255;
        for (let component = 0; component < 3; component++) {
            assert.ok(Math.abs(values[channel * 5 + component] - [0.2126, 0.7152, 0.0722][component] * tint) < 1e-12);
        }
        assert.deepStrictEqual(values.slice(channel * 5 + 3, channel * 5 + 5), [0, 0]);
    }
    assert.deepStrictEqual(values.slice(15), [0, 0, 0, 1, 0], 'alpha must remain unchanged');
}

assert.deepStrictEqual(state(), { brightness: 1, monoEnabled: false, monoColor: '#ffffff' });
assert.strictEqual(properties['--map-brightness-user'], '1');
assert.strictEqual(properties['--map-mono-filter'], 'brightness(1)');
for (const percent of [0, 1, 50, 100, 150, 200]) {
    input('map-brightness', String(percent));
    assert.strictEqual(Number(properties['--map-brightness-user']), percent / 100);
    assert.strictEqual(element('map-brightness-value').textContent, `${percent}%`);
}
const unrelatedBefore = JSON.stringify(['hud', 'radar-canvas', 'map-container', 'trail-min', 'trail-max'].map(element));
element('btn-mono-map').click();
assert.strictEqual(properties['--map-mono-filter'], 'url(#map-mono-filter)');
assert.strictEqual(element('btn-mono-map').attributes['aria-pressed'], 'true');
assert.ok(element('btn-mono-map').classes.has('active'));
for (const tint of ['#ffffff', '#000000', '#808080', '#ff0000', '#00ff00', '#0000ff', '#38bdf8']) {
    assertTint(tint);
}
input('map-brightness', '150');
element('btn-mono-map').click();
assert.strictEqual(properties['--map-mono-filter'], 'brightness(1)');
assert.strictEqual(element('btn-mono-map').attributes['aria-pressed'], 'false');
assert.ok(!element('btn-mono-map').classes.has('active'));
assertTint('#ff8800');
assert.strictEqual(properties['--map-mono-filter'], 'brightness(1)', 'picker must not enable mono');
element('btn-mono-map').click();
assert.strictEqual(state().brightness, 1.5);
assert.strictEqual(state().monoColor, '#ff8800');
assert.strictEqual(JSON.stringify(['hud', 'radar-canvas', 'map-container', 'trail-min', 'trail-max'].map(element)), unrelatedBefore,
    'visual controls must not mutate unrelated elements');
assert.deepStrictEqual(Object.keys(properties).sort(), ['--map-brightness-user', '--map-mono-filter']);

async function testModeChanges() {
    const chosenState = state();
    context.toggleNightMode();
    assert.strictEqual(properties['--night-map-brightness'], '0.4');
    resolveConfig({ ok: true, json: () => Promise.resolve({ brightness_map: 0.25, brightness_elements: 0.6, brightness_trails: 0.7 }) });
    await new Promise(resolve => setImmediate(resolve));
    assert.strictEqual(properties['--night-map-brightness'], '0.25', 'late config applies during night mode');
    input('map-brightness', '120');
    assert.strictEqual(properties['--night-map-brightness'], '0.25', 'slider must not overwrite night brightness');
    assert.strictEqual(Number(properties['--map-brightness-user']) * Number(properties['--night-map-brightness']), 0.3);
    input('map-brightness', '150');
    assert.strictEqual(vm.runInContext('nightBrightness.brightness_elements', context), 0.6);
    assert.strictEqual(vm.runInContext('nightBrightness.brightness_trails', context), 0.7);
    context.toggleNightMode();
    assert.strictEqual(properties['--night-map-brightness'], '1');
    assert.deepStrictEqual(state(), chosenState);
    for (const name of ['osm', 'esri-imagery', 'carto-light', 'esri-topo', 'carto-voyager', 'carto-dark']) {
        element('map-style-dropdown').change({ target: { value: name } });
        assert.strictEqual(layers.size, name.startsWith('carto-') && name !== 'carto-voyager' ? 2 : 1);
        assert.deepStrictEqual(state(), chosenState, 'basemap switching preserves all visual values');
        assert.strictEqual(properties['--map-mono-filter'], 'url(#map-mono-filter)');
    }
    context.toggleMap();
    context.toggleMap();
    context.toggleOsd();
    context.toggleOsd();
    assert.deepStrictEqual(state(), chosenState, 'map/off-grid and OSD toggles preserve visual values');
    assert.strictEqual(element('map-brightness').value, '150');
    assert.strictEqual(element('map-mono-color').value, '#ff8800');
    assert.strictEqual(element('btn-mono-map').attributes['aria-pressed'], 'true');
    console.log('map_visuals_regression: OK');
}
testModeChanges().catch(error => { console.error(error); process.exitCode = 1; });
