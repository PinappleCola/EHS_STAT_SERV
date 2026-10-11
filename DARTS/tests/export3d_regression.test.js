const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
const start = liveMap.indexOf('async function exportTrail3DGeoJSON()');
const end = liveMap.indexOf("document.getElementById('btn-export-geojson-3d')", start);
assert.ok(start >= 0 && end > start);
const source = liveMap.slice(start, end);
assert.doesNotMatch(source, /JSON\.parse|blob\.text/);

async function download(disposition, fail = false) {
    const messages = [];
    const anchor = { click() { this.clicked = true; } };
    let downloadedBlob;
    let revoked = false;
    const bytes = new TextEncoder().encode('{"type":"FeatureCollection","features":[]}');
    const context = {
        HTTP_API: 'http://localhost',
        getTrailRangeWindow: () => ({ fromMs: 1000, toMs: 2000 }),
        URLSearchParams, ReadableStream, Response,
        fetch: async () => ({
            ok: true,
            headers: { get: () => disposition },
            body: new ReadableStream({
                start(controller) {
                    controller.enqueue(bytes.slice(0, 10));
                    if (fail) controller.error(new Error('connection lost'));
                    else {
                        controller.enqueue(bytes.slice(10));
                        controller.close();
                    }
                }
            })
        }),
        console: { info: message => messages.push(message) },
        document: { createElement: () => anchor },
        URL: {
            createObjectURL(blob) { downloadedBlob = blob; return 'blob:export'; },
            revokeObjectURL() { revoked = true; }
        },
        setTimeout(callback) { callback(); }
    };
    vm.createContext(context);
    const promise = vm.runInContext(`${source}\nexportTrail3DGeoJSON()`, context);
    if (fail) {
        await assert.rejects(promise, /connection lost/);
        assert.ok(!anchor.clicked);
        return;
    }
    await promise;
    assert.strictEqual(await downloadedBlob.text(), new TextDecoder().decode(bytes));
    assert.ok(anchor.clicked && revoked);
    assert.ok(messages.some(message => message.includes('MiB received')));
    assert.ok(messages.some(message => message.includes('download complete')));
    return anchor.download;
}

(async () => {
    assert.strictEqual(await download('attachment; filename="3DSPAT_test_00F4.geojson"'),
        '3DSPAT_test_00F4.geojson');
    assert.strictEqual(await download("attachment; filename*=UTF-8''..%2Fsafe.geojson"),
        'safe.geojson');
    assert.match(await download(''), /^3DSPAT_.*_0000\.geojson$/);
    await download('', true);
    console.log('export3d_regression: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
