const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
const start = liveMap.indexOf('        // --- Aircraft data-tag styling');
const end = liveMap.indexOf('        let nightBrightness', start);
assert.ok(start >= 0 && end > start);
const source = liveMap.slice(start, end);
const defaults = { font_family: 'B612 Mono', font_size_px: 11, text_colour: null };
const custom = { font_family: 'Courier New', font_size_px: 22, text_colour: '#ffd166' };

async function load(fetch) {
    const context = vm.createContext({ fetch, HTTP_API: 'http://localhost:8766', console: { warn() {} } });
    vm.runInContext(source, context);
    await new Promise(resolve => setImmediate(resolve));
    return context;
}
const state = context => JSON.parse(vm.runInContext('JSON.stringify(dataTagStyle)', context));

(async () => {
    const context = await load(async url => {
        assert.strictEqual(url, 'http://localhost:8766/api/data-tag-style');
        return { ok: true, json: async () => custom };
    });
    assert.deepStrictEqual(state(context), custom);
    for (const fetch of [
        async () => { throw new Error('offline'); },
        async () => ({ ok: false }),
        async () => ({ ok: true, json: async () => { throw new Error('bad JSON'); } }),
        async () => ({ ok: true, json: async () => null }),
    ]) {
        assert.deepStrictEqual(state(await load(fetch)), defaults);
    }
    const normalize = raw => JSON.parse(vm.runInContext(`JSON.stringify(normalizeDataTagStyle(${raw}))`, context));
    for (const raw of ['null', '[]', '{}', 'false']) assert.deepStrictEqual(normalize(raw), defaults);
    for (const [key, invalidValues] of Object.entries({
        font_family: ['null', '""', '12', '"Arial, serif"', '"A; 40px serif"', JSON.stringify('A'.repeat(101))],
        font_size_px: ['null', '"16"', 'true', '7', '33', 'NaN', 'Infinity'],
        text_colour: ['"red"', '"currentColor"', '"#abcd"', '"#xyz"', '"#abc\\n"', '123'],
    })) {
        for (const value of invalidValues) {
            const raw = `{...${JSON.stringify(custom)}, ${key}: ${value}}`;
            assert.deepStrictEqual(normalize(raw), { ...custom, [key]: defaults[key] });
        }
    }
    for (const size of [8, 11.5, 32]) assert.strictEqual(normalize(`{font_size_px: ${size}}`).font_size_px, size);
    assert.strictEqual(normalize('{text_colour: "#AbC"}').text_colour, '#AbC');

    const measuredFonts = [];
    const ctx = {
        font: '99px unrelated',
        measureText(text) {
            measuredFonts.push(this.font);
            const size = parseFloat(this.font.replace(/^bold /, ''));
            return { width: text.length * size * 0.6, actualBoundingBoxAscent: size * 0.7, actualBoundingBoxDescent: size * 0.2 };
        },
    };
    context.ctx = ctx;
    const layout = selected => JSON.parse(vm.runInContext(`JSON.stringify(measureDataTag(ctx, ['CALLSIGN', 'FL120', '7700'], ${selected}))`, context));
    vm.runInContext('dataTagStyle = {...DEFAULT_DATA_TAG_STYLE}', context);
    const normal = layout(false);
    assert.strictEqual(normal.font, "11px 'B612 Mono', 'B612 Mono', 'Consolas', monospace");
    assert.strictEqual(normal.lineHeight, 11.5);
    assert.strictEqual(normal.baseline, 7);
    assert.strictEqual(normal.height, 49);
    assert.strictEqual(normal.width, Math.ceil(8 * 11 * 0.6 + 14));
    vm.runInContext(`dataTagStyle = normalizeDataTagStyle(${JSON.stringify(custom)})`, context);
    const large = layout(true);
    assert.strictEqual(large.font, "bold 22px 'Courier New', 'B612 Mono', 'Consolas', monospace");
    assert.ok(measuredFonts.slice(-3).every(font => font === large.font));
    assert.strictEqual(large.lineHeight, 23);
    assert.strictEqual(large.padX, 12);
    assert.strictEqual(large.padY, 14);
    assert.strictEqual(large.height, 97);
    assert.ok(large.width > normal.width);
    assert.ok(large.padY + large.baseline + 2 * large.lineHeight + 22 * 0.2 < large.height);
    const colour = (key, plane = {}, selected = false, ra = false) =>
        vm.runInContext(`dataTagTextColour({key: '${key}'}, ${JSON.stringify(plane)}, ${selected}, ${ra})`, context);
    assert.strictEqual(colour('callsign'), '#ffd166');
    assert.strictEqual(colour('callsign', { is_coasting: true }), '#ffd166');
    assert.strictEqual(colour('callsign', {}, true), '#ffffff');
    for (const squawk of ['7500', '7600', '7700']) {
        assert.strictEqual(colour('squawk', { squawk }, true), '#ef4444');
    }
    assert.strictEqual(colour('tcas_ra', {}, true, true), '#ef4444');
    vm.runInContext('dataTagStyle = {...DEFAULT_DATA_TAG_STYLE}', context);
    assert.strictEqual(colour('callsign'), '#38bdf8');
    assert.strictEqual(colour('callsign', { is_coasting: true }), 'rgba(148, 163, 184, 0.9)');

    // Extreme glyph metrics must expand line spacing and bounds, not clip/overlap.
    ctx.measureText = () => ({ width: 100, actualBoundingBoxAscent: 30, actualBoundingBoxDescent: 10 });
    const tall = layout(false);
    assert.ok(tall.lineHeight > 40);
    assert.ok(tall.padY + tall.baseline >= 30);
    assert.ok(tall.padY + tall.baseline + 2 * tall.lineHeight + 10 <= tall.height - tall.padY);

    // Exercise the actual drawing block with a canvas spy.
    const drawStart = liveMap.indexOf('                            // Measure content to dynamically size box');
    const drawEnd = liveMap.indexOf('\n                        }', drawStart);
    const drawSource = liveMap.slice(drawStart, drawEnd);
    const draws = [];
    Object.assign(ctx, {
        beginPath() {}, roundRect(...args) { this.box = args; }, fill() {}, stroke() {},
        moveTo() {}, lineTo() {},
        fillText(text, x, y) { draws.push({ text, x, y, font: this.font, colour: this.fillStyle }); },
    });
    Object.assign(context, {
        rCtx: ctx, lines: ['ABC', '7700'], lineEntries: [{ key: 'callsign', text: 'ABC' }, { key: 'squawk', text: '7700' }],
        isSelected: false, isDimmed: false, hasActiveRa: false,
        p: { squawk: '7700' }, pt: { x: 100, y: 100 }, occupiedRects: [], mapTagShowBox: true,
    });
    vm.runInContext(`dataTagStyle = normalizeDataTagStyle(${JSON.stringify(custom)})`, context);
    vm.runInContext(`(() => { ${drawSource} })()`, context);
    assert.strictEqual(draws.length, 2);
    assert.ok(draws.every(draw => draw.font.startsWith("22px 'Courier New'")));
    assert.deepStrictEqual(draws.map(draw => draw.colour), ['#ffd166', '#ef4444']);
    assert.ok(draws[1].y - draws[0].y >= 40);
    assert.strictEqual(context.occupiedRects[0].w, ctx.box[2]);
    assert.strictEqual(context.occupiedRects[0].h, ctx.box[3]);
    assert.ok(draws[1].y + 10 <= ctx.box[1] + ctx.box[3]);
    ctx.box = null;
    context.mapTagShowBox = false;
    context.occupiedRects = [];
    vm.runInContext(`(() => { ${drawSource} })()`, context);
    assert.strictEqual(ctx.box, null, 'box toggle must remain independent of text');
    assert.strictEqual(draws.length, 4);
    console.log('data_tag_style_regression: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
