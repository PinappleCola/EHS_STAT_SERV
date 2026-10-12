const assert = require('assert');
const path = require('path');

const pluginDir = path.join(__dirname, '..', 'streamdeck', 'plugin', 'com.pinapplecola.darts.sdPlugin');
const manifest = require(path.join(pluginDir, 'manifest.json'));
const state = require(path.join(pluginDir, 'bin', 'state.js'));
const { DartsPlugin, normalizeBaseUrl, parseArgs } = require(path.join(pluginDir, 'bin', 'plugin.js'));

// --- Manifest exposes exactly the MAP / IFR / VFR actions the plugin handles ---
assert.strictEqual(manifest.CodePath, 'bin/plugin.js');
assert.deepStrictEqual(manifest.Actions.map((a) => a.UUID).sort(), Object.keys(state.ACTIONS).sort());
for (const action of manifest.Actions) assert.ok(action.UUID.startsWith(`${manifest.UUID}.`));

// --- State model ---
let uuidSeq = 0;
const randomUUID = () => `uuid-${++uuidSeq}`;
const snapshot = (extra) => ({
    connectionState: 'connected', mapEnabled: true, ifrEnabled: false, vfrEnabled: true,
    lastRequestId: null, revision: 1, ...extra,
});

let model = state.createModel();
assert.strictEqual(model.connectionState, 'offline');
for (const control of ['map', 'ifr', 'vfr']) assert.strictEqual(state.keyStatus(model, control, 0), 'offline');
assert.deepStrictEqual(state.beginCommand(model, 'ifr', 0, randomUUID), { ok: false, reason: 'offline' });

state.applySnapshot(model, snapshot());
assert.strictEqual(state.keyStatus(model, 'map', 0), 'on');
assert.strictEqual(state.keyStatus(model, 'ifr', 0), 'off');
assert.strictEqual(state.keyStatus(model, 'vfr', 0), 'on');

state.applySnapshot(model, snapshot({ connectionState: 'no_map', mapEnabled: null, ifrEnabled: null, vfrEnabled: null }));
assert.strictEqual(state.keyStatus(model, 'ifr', 0), 'no_map');
assert.deepStrictEqual(state.beginCommand(model, 'ifr', 0, randomUUID), { ok: false, reason: 'no_map' });
state.applySnapshot(model, snapshot({ connectionState: 'stale' }));
assert.strictEqual(state.keyStatus(model, 'ifr', 0), 'stale');
state.applySnapshot(model, { connectionState: 'bogus' });
assert.strictEqual(model.connectionState, 'offline');
assert.strictEqual(model.ifrEnabled, null);

// Press -> pending until the map echoes the request ID; no guessed state.
state.applySnapshot(model, snapshot());
const begin = state.beginCommand(model, 'ifr', 1000, randomUUID);
assert.deepStrictEqual(begin, { ok: true, requestId: 'sd-uuid-1', command: 'toggle_ifr' });
assert.strictEqual(state.keyStatus(model, 'ifr', 1000), 'pending');
assert.strictEqual(state.keyStatus(model, 'map', 1000), 'on', 'other keys keep their live state');
assert.deepStrictEqual(state.beginCommand(model, 'map', 1000, randomUUID), { ok: false, reason: 'pending' });
state.applySnapshot(model, snapshot({ ifrEnabled: true, lastRequestId: 'other' }));
assert.strictEqual(state.keyStatus(model, 'ifr', 1100), 'pending', 'unrelated reports do not confirm');
state.applySnapshot(model, snapshot({ ifrEnabled: true, lastRequestId: 'sd-uuid-1' }));
assert.strictEqual(model.pendingCommand, null);
assert.strictEqual(state.keyStatus(model, 'ifr', 1200), 'on');

// Unconfirmed commands time out into ERROR, then fall back to the live state.
const timed = state.beginCommand(model, 'vfr', 2000, randomUUID);
assert.ok(timed.ok);
assert.strictEqual(state.expirePending(model, 2000 + state.TIMING.confirmTimeoutMs - 1), false);
assert.strictEqual(state.expirePending(model, 2000 + state.TIMING.confirmTimeoutMs), true);
assert.strictEqual(model.pendingCommand, null);
assert.strictEqual(state.keyStatus(model, 'vfr', 5001), 'error');
assert.strictEqual(state.keyStatus(model, 'vfr', 5000 + state.TIMING.errorHoldMs + 1), 'on');
const failed = state.beginCommand(model, 'map', 9000, randomUUID);
assert.strictEqual(state.failCommand(model, 'not-ours', 9000), false);
assert.strictEqual(state.failCommand(model, failed.requestId, 9000), true);
assert.strictEqual(state.keyStatus(model, 'map', 9001), 'error');

// --- Rendering & settings ---
const colorsOf = (svg) => /<rect[^>]*fill="([^"]+)"/.exec(svg)[1];
const D = state.DEFAULT_COLORS;
for (const [status, color, text] of [
    ['on', D.colorOn, 'ON'], ['off', D.colorOff, 'OFF'], ['pending', D.colorPending, 'WAIT'],
    ['error', D.colorPending, 'ERROR'], ['offline', D.colorOffline, 'OFFLINE'],
    ['no_map', D.colorNoMap, 'NO MAP'], ['stale', D.colorNoMap, 'STALE'],
]) {
    const svg = state.renderKeySvg('ifr', status, {});
    assert.strictEqual(colorsOf(svg), color, status);
    assert.ok(svg.includes(`>${text}</text>`), status);
    assert.ok(svg.includes('>IFR</text>'));
}
const custom = state.renderKeySvg('map', 'on', { label: ' <B&> ', colorOn: '#00ff00', colorOff: 'red" onload="x' });
assert.strictEqual(colorsOf(custom), '#00ff00');
assert.ok(custom.includes('>&lt;B&amp;&gt;</text>'));
assert.strictEqual(colorsOf(state.renderKeySvg('map', 'off', { colorOff: 'red" onload="x' })), D.colorOff);
assert.strictEqual(state.normalizeSettings('vfr', { label: 'ABCDEFGHIJKLMN' }).label, 'ABCDEFGHIJ');
const icon = 'data:image/png;base64,iVBORw0KGgo=';
assert.ok(state.renderKeySvg('vfr', 'on', {}, icon).includes(`<image href="${icon}"`));
assert.ok(!state.renderKeySvg('vfr', 'on', {}, 'javascript:alert(1)').includes('<image'));
assert.ok(state.svgToImage('<svg/>').startsWith('data:image/svg+xml;charset=utf8,'));

// --- Plugin runtime with fake Stream Deck + DARTS ---
assert.strictEqual(normalizeBaseUrl(''), 'http://127.0.0.1:8766');
assert.strictEqual(normalizeBaseUrl('http://localhost:9000/x'), 'http://localhost:9000');
assert.strictEqual(normalizeBaseUrl('file:///etc/passwd'), 'http://127.0.0.1:8766');
assert.deepStrictEqual(parseArgs(['-port', '1234', '-pluginUUID', 'abc', '-registerEvent', 'registerPlugin']),
    { port: '1234', pluginUUID: 'abc', registerEvent: 'registerPlugin' });

async function runPluginScenario() {
    let clock = 0;
    let darts = { up: true, state: snapshot({ ifrEnabled: false }), commands: [], commandStatus: 200 };
    const timers = [];
    const sent = [];
    const fakeFetch = async (url, options = {}) => {
        if (!darts.up) throw new Error('ECONNREFUSED');
        if (url.endsWith('/api/ui-state')) return { ok: true, status: 200, json: async () => ({ ...darts.state }) };
        if (url.endsWith('/api/ui-command')) {
            darts.commands.push(JSON.parse(options.body));
            return { ok: darts.commandStatus === 200, status: darts.commandStatus, json: async () => ({}) };
        }
        throw new Error(`unexpected ${url}`);
    };
    const plugin = new DartsPlugin({
        send: (msg) => sent.push(msg), fetch: fakeFetch, now: () => clock, randomUUID,
        setTimeout: (fn) => { timers.push(fn); return timers.length; }, clearTimeout: () => {},
        readIcon: () => { throw new Error('missing'); },
    });
    const runTimers = async () => {
        // Run exactly one scheduled poll (each poll schedules the next one).
        const fn = timers.pop();
        timers.length = 0;
        if (fn) await fn();
    };
    const lastImage = (context) => {
        const msgs = sent.filter((m) => m.event === 'setImage' && m.context === context);
        return msgs.length ? msgs[msgs.length - 1].payload.image : '';
    };
    const statusOf = (context) => /font-size="22">([^<]*)<\/text>/.exec(lastImage(context))[1];

    plugin.start();
    plugin.handleDeckMessage({ event: 'willAppear', action: 'com.pinapplecola.darts.map', context: 'k-map', payload: { settings: {} } });
    plugin.handleDeckMessage({ event: 'willAppear', action: 'com.pinapplecola.darts.ifr', context: 'k-ifr', payload: { settings: { icon: 'C:/none.png' } } });
    plugin.handleDeckMessage({ event: 'willAppear', action: 'com.example.other', context: 'k-other', payload: {} });
    assert.strictEqual(statusOf('k-ifr'), 'OFFLINE', 'keys start offline until DARTS answers');
    assert.ok(sent.some((m) => m.event === 'logMessage' && m.payload.message.includes('icon override not loaded')));
    await runTimers();
    timers.length = 0;
    assert.strictEqual(statusOf('k-map'), 'ON');
    assert.strictEqual(statusOf('k-ifr'), 'OFF');
    assert.ok(!sent.some((m) => m.context === 'k-other'));

    // Press IFR: command carries a request ID; key goes amber until the map confirms.
    const imagesBefore = sent.filter((m) => m.event === 'setImage').length;
    await plugin.handleDeckMessage({ event: 'keyDown', action: 'com.pinapplecola.darts.ifr', context: 'k-ifr', payload: {} });
    assert.strictEqual(darts.commands.length, 1);
    assert.strictEqual(darts.commands[0].command, 'toggle_ifr');
    assert.match(darts.commands[0].request_id, /^sd-uuid-\d+$/);
    assert.strictEqual(darts.commands[0].request_id, plugin.model.pendingCommand.requestId);
    assert.strictEqual(statusOf('k-ifr'), 'WAIT');
    assert.ok(sent.filter((m) => m.event === 'setImage').length > imagesBefore);
    await runTimers();
    assert.strictEqual(statusOf('k-ifr'), 'WAIT', 'no guessing while the map has not confirmed');
    darts.state = snapshot({ ifrEnabled: true, lastRequestId: darts.commands[0].request_id });
    await runTimers();
    assert.strictEqual(statusOf('k-ifr'), 'ON');

    // Mouse clicks on the ribbon are picked up by the next poll.
    darts.state = snapshot({ mapEnabled: false, ifrEnabled: true });
    await runTimers();
    assert.strictEqual(statusOf('k-map'), 'OFF');

    // No confirmation within the timeout -> ERROR + alert, then re-sync to live state.
    await plugin.handleDeckMessage({ event: 'keyDown', action: 'com.pinapplecola.darts.map', context: 'k-map', payload: {} });
    assert.strictEqual(statusOf('k-map'), 'WAIT');
    clock += state.TIMING.confirmTimeoutMs;
    await runTimers();
    assert.strictEqual(statusOf('k-map'), 'ERROR');
    assert.ok(sent.some((m) => m.event === 'showAlert' && m.context === 'k-map'));
    clock += state.TIMING.errorHoldMs + 1;
    await runTimers();
    assert.strictEqual(statusOf('k-map'), 'OFF');

    // HTTP failure -> immediate ERROR.
    darts.commandStatus = 503;
    await plugin.handleDeckMessage({ event: 'keyDown', action: 'com.pinapplecola.darts.map', context: 'k-map', payload: {} });
    assert.strictEqual(statusOf('k-map'), 'ERROR');
    darts.commandStatus = 200;
    clock += state.TIMING.errorHoldMs + 1;

    // No map / offline: no command is sent, key shows the connection state.
    darts.state = { connectionState: 'no_map', mapEnabled: null, ifrEnabled: null, vfrEnabled: null };
    await runTimers();
    assert.strictEqual(statusOf('k-map'), 'NO MAP');
    const commandCount = darts.commands.length;
    sent.length = 0;
    await plugin.handleDeckMessage({ event: 'keyDown', action: 'com.pinapplecola.darts.ifr', context: 'k-ifr', payload: {} });
    assert.strictEqual(darts.commands.length, commandCount);
    assert.ok(sent.some((m) => m.event === 'showAlert' && m.context === 'k-ifr'));
    darts.up = false;
    await runTimers();
    assert.strictEqual(statusOf('k-ifr'), 'OFFLINE');

    // Map reconnects -> live state again; settings change re-renders with new colour/label.
    darts.up = true;
    darts.state = snapshot({ ifrEnabled: true });
    await runTimers();
    assert.strictEqual(statusOf('k-ifr'), 'ON');
    plugin.handleDeckMessage({ event: 'didReceiveSettings', action: 'com.pinapplecola.darts.ifr', context: 'k-ifr', payload: { settings: { label: 'IFR WP', colorOn: '#123456' } } });
    assert.ok(lastImage('k-ifr').includes('fill="#123456"'));
    assert.ok(lastImage('k-ifr').includes('>IFR WP</text>'));

    // Global DARTS URL setting is applied to subsequent requests.
    const urls = [];
    plugin.fetch = async (url, options) => { urls.push(url); return fakeFetch(url, options); };
    plugin.handleDeckMessage({ event: 'didReceiveGlobalSettings', payload: { settings: { dartsUrl: 'http://localhost:9999' } } });
    await runTimers();
    assert.ok(urls.includes('http://localhost:9999/api/ui-state'));
    plugin.handleDeckMessage({ event: 'willDisappear', context: 'k-ifr' });
    assert.ok(!plugin.contexts.has('k-ifr'));
    plugin.stop();
}

runPluginScenario().then(() => {
    console.log('streamdeck_plugin_regression: OK');
}).catch((err) => {
    console.error(err);
    process.exit(1);
});
