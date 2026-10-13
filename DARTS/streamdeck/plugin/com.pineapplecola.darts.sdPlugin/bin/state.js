'use strict';

// DARTS Stream Deck plugin: state model and key-face rendering.
// Pure functions only (no Stream Deck / network access) so they can be tested.

const CONTROLS = {
    map: { command: 'toggle_map', stateKey: 'mapEnabled', label: 'MAP' },
    ifr: { command: 'toggle_ifr', stateKey: 'ifrEnabled', label: 'IFR' },
    vfr: { command: 'toggle_vfr', stateKey: 'vfrEnabled', label: 'VFR' },
    span_30m: { command: 'span_30m', stateKey: 'activeSpan', stateValue: '30m', label: '30MIN' },
    span_1h: { command: 'span_1h', stateKey: 'activeSpan', stateValue: '1h', label: '1HR' },
    span_2h: { command: 'span_2h', stateKey: 'activeSpan', stateValue: '2h', label: '2HR' },
    span_4h: { command: 'span_4h', stateKey: 'activeSpan', stateValue: '4h', label: '4HR' },
    span_day: { command: 'span_day', stateKey: 'activeSpan', stateValue: 'day', label: 'DAY' },
    night: { command: 'toggle_night', stateKey: 'nightMode', label: 'NIGHT' },
    osd: { command: 'toggle_osd', stateKey: 'osdVisible', label: 'OSD' },
    export3d: { command: 'export_3d', stateKey: 'exportState', label: 'EXPORT 3D' },
};

const ACTIONS = {
    'com.pineapplecola.darts.map': 'map',
    'com.pineapplecola.darts.ifr': 'ifr',
    'com.pineapplecola.darts.vfr': 'vfr',
    'com.pineapplecola.darts.span30m': 'span_30m',
    'com.pineapplecola.darts.span1h': 'span_1h',
    'com.pineapplecola.darts.span2h': 'span_2h',
    'com.pineapplecola.darts.span4h': 'span_4h',
    'com.pineapplecola.darts.spanday': 'span_day',
    'com.pineapplecola.darts.night': 'night',
    'com.pineapplecola.darts.osd': 'osd',
    'com.pineapplecola.darts.export3d': 'export3d',
};

const CONNECTION_STATES = new Set(['connected', 'offline', 'no_map', 'stale']);

const TIMING = {
    pollMs: 1000,          // normal /api/ui-state poll interval
    pendingPollMs: 250,    // faster poll while waiting for confirmation
    requestTimeoutMs: 1500,
    confirmTimeoutMs: 3000,
    errorHoldMs: 1500,     // how long ERROR is shown before returning to live state
};

const DEFAULT_COLORS = {
    colorOn: '#15803D',      // enabled / visible
    colorOff: '#B91C1C',     // disabled / hidden
    colorPending: '#B45309', // waiting for confirmation (also ERROR)
    colorOffline: '#CBD5E1', // DARTS unreachable (calm neutral light)
    colorNoMap: '#475569',   // DARTS up, but no live map (or its state is stale)
    colorWorking: '#B45309',
    colorDone: '#15803D',
    colorFailed: '#B91C1C',
};

const STATUS_TEXT = {
    on: 'ON', off: 'OFF', pending: 'WAIT', error: 'ERROR',
    offline: 'OFFLINE', no_map: 'NO MAP', stale: 'STALE',
    working: 'WORKING…', done: '✓ DONE', failed: '✗ FAIL', ready: 'READY',
};

const STATUS_COLOR_KEY = {
    on: 'colorOn', off: 'colorOff', pending: 'colorPending', error: 'colorPending',
    offline: 'colorOffline', no_map: 'colorNoMap', stale: 'colorNoMap',
    working: 'colorWorking', done: 'colorDone', failed: 'colorFailed', ready: 'colorNoMap',
};

const STATUS_IMAGE_KEY = {
    on: 'imageOn', off: 'imageOff', pending: 'imagePending', error: 'imageError',
    offline: 'imageOffline', no_map: 'imageNoMap', stale: 'imageStale',
};

const COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const ICON_DATA_URI_RE = /^data:image\/(?:png|jpeg|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$/;
const MAX_LABEL_LENGTH = 10;

function createModel() {
    return {
        mapEnabled: null,
        ifrEnabled: null,
        vfrEnabled: null,
        activeSpan: null,
        nightMode: false,
        osdVisible: true,
        exportState: 'idle',
        exportProgress: null,
        connectionState: 'offline',
        lastRequestId: null,
        revision: null,
        pendingCommand: null, // { requestId, control, command, sentAt }
        errors: {},           // control -> timestamp until which ERROR is shown
    };
}

function applySnapshot(model, snapshot) {
    if (!snapshot || typeof snapshot !== 'object' || !CONNECTION_STATES.has(snapshot.connectionState)) {
        markOffline(model);
        return;
    }
    model.connectionState = snapshot.connectionState;
    for (const { stateKey } of Object.values(CONTROLS)) {
        if (stateKey === 'activeSpan') {
            model.activeSpan = typeof snapshot.activeSpan === 'string' ? snapshot.activeSpan : null;
        } else if (stateKey === 'exportState') {
            model.exportState = ['idle', 'working', 'done', 'error'].includes(snapshot.exportState) ? snapshot.exportState : 'idle';
        } else {
            model[stateKey] = typeof snapshot[stateKey] === 'boolean' ? snapshot[stateKey] : null;
        }
    }
    model.nightMode = snapshot.nightMode === true;
    model.osdVisible = typeof snapshot.osdVisible === 'boolean' ? snapshot.osdVisible : true;
    model.exportProgress = typeof snapshot.exportProgress === 'number' && Number.isFinite(snapshot.exportProgress)
        && snapshot.exportProgress >= 0 && snapshot.exportProgress <= 100 ? snapshot.exportProgress : null;
    model.lastRequestId = typeof snapshot.lastRequestId === 'string' ? snapshot.lastRequestId : null;
    model.revision = typeof snapshot.revision === 'number' ? snapshot.revision : null;
    if (model.pendingCommand && model.lastRequestId === model.pendingCommand.requestId) {
        model.pendingCommand = null; // the map confirmed our command; its reported state is final
    }
}

function markOffline(model) {
    model.connectionState = 'offline';
    for (const { stateKey } of Object.values(CONTROLS)) model[stateKey] = null;
    model.activeSpan = null;
    model.nightMode = false;
    model.osdVisible = true;
    model.exportState = 'idle';
    model.exportProgress = null;
    model.lastRequestId = null;
    model.revision = null;
}

// Returns { ok: true, requestId, command } or { ok: false, reason }.
function beginCommand(model, control, now, randomUUID) {
    const spec = CONTROLS[control];
    if (!spec) return { ok: false, reason: 'unknown_control' };
    if (model.pendingCommand) return { ok: false, reason: 'pending' };
    if (control === 'export3d' && model.exportState === 'working') return { ok: false, reason: 'busy' };
    if (model.connectionState !== 'connected') return { ok: false, reason: model.connectionState };
    const requestId = `sd-${randomUUID()}`;
    model.pendingCommand = { requestId, control, command: spec.command, sentAt: now };
    delete model.errors[control];
    return { ok: true, requestId, command: spec.command };
}

function failCommand(model, requestId, now) {
    const pending = model.pendingCommand;
    if (!pending || pending.requestId !== requestId) return false;
    model.pendingCommand = null;
    model.errors[pending.control] = now + TIMING.errorHoldMs;
    return true;
}

function expirePending(model, now) {
    const pending = model.pendingCommand;
    if (!pending || now - pending.sentAt < TIMING.confirmTimeoutMs) return false;
    return failCommand(model, pending.requestId, now);
}

function keyStatus(model, control, now) {
    const spec = CONTROLS[control];
    if ((model.errors[control] || 0) > now) return 'error';
    if (model.connectionState !== 'connected') return model.connectionState;
    const value = spec ? model[spec.stateKey] : null;
    if (spec && spec.stateKey === 'activeSpan') return model.activeSpan === spec.stateValue ? 'on' : 'off';
    if (spec && spec.stateKey === 'exportState') {
        if (model.exportState === 'working' || model.exportState === 'done') return model.exportState;
        if (model.exportState === 'error') return 'failed';
        return 'ready';
    }
    if (value === true) return 'on';
    if (value === false) return 'off';
    return 'stale';
}

function normalizeSettings(control, settings) {
    const src = settings && typeof settings === 'object' ? settings : {};
    const label = typeof src.label === 'string' ? src.label.trim().slice(0, MAX_LABEL_LENGTH) : '';
    const out = { label: label || (CONTROLS[control] ? CONTROLS[control].label : '?') };
    for (const [key, fallback] of Object.entries(DEFAULT_COLORS)) {
        out[key] = typeof src[key] === 'string' && COLOR_RE.test(src[key].trim()) ? src[key].trim() : fallback;
    }
    out.icon = typeof src.icon === 'string' ? src.icon.trim() : '';
    for (const key of Object.values(STATUS_IMAGE_KEY)) {
        out[key] = typeof src[key] === 'string' ? src[key].trim() : '';
    }
    return out;
}

function imagePathFor(status, settings) {
    return Object.hasOwn(STATUS_IMAGE_KEY, status) ? settings[STATUS_IMAGE_KEY[status]] : '';
}

function escapeXml(text) {
    return String(text).replace(/[<>&'"]/g, (ch) => ({
        '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;',
    }[ch]));
}

function textColorForBackground(bgHex) {
    if (typeof bgHex !== 'string') return '#FFFFFF';
    let clean = bgHex.trim().replace(/^#/, '');
    if (clean.length === 3) {
        clean = clean.split('').map((c) => c + c).join('');
    }
    if (clean.length !== 6) return '#FFFFFF';
    const num = parseInt(clean, 16);
    if (Number.isNaN(num)) return '#FFFFFF';
    const r = (num >> 16) & 255;
    const g = (num >> 8) & 255;
    const b = num & 255;
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    return lum > 160 ? '#0F172A' : '#FFFFFF';
}

function renderKeySvg(control, status, settings, iconDataUri, progress = null) {
    const s = normalizeSettings(control, settings);
    const background = s[STATUS_COLOR_KEY[status] || 'colorOffline'];
    const hasIcon = typeof iconDataUri === 'string' && ICON_DATA_URI_RE.test(iconDataUri);
    const baseSize = hasIcon ? 34 : 52;
    const labelSize = s.label.length > 3 ? Math.max(16, Math.floor(baseSize * 3 / s.label.length)) : baseSize;
    const textColor = textColorForBackground(background);
    const font = `font-family="Arial, Helvetica, sans-serif" font-weight="bold" fill="${textColor}" text-anchor="middle"`;
    return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">',
        `<rect width="144" height="144" rx="18" fill="${background}"/>`,
        hasIcon ? `<image href="${iconDataUri}" x="46" y="8" width="52" height="52" preserveAspectRatio="xMidYMid meet"/>` : '',
        `<text x="72" y="${hasIcon ? 96 : 82}" ${font} font-size="${labelSize}">${escapeXml(s.label)}</text>`,
        `<text x="72" y="${hasIcon ? 128 : 120}" ${font} font-size="22">${status === 'working' && Number.isFinite(progress) ? `${Math.round(progress)}%` : (STATUS_TEXT[status] || '')}</text>`,
        '</svg>',
    ].join('');
}

function svgToImage(svg) {
    return `data:image/svg+xml;charset=utf8,${svg}`;
}

module.exports = {
    ACTIONS,
    CONTROLS,
    DEFAULT_COLORS,
    STATUS_TEXT,
    TIMING,
    applySnapshot,
    beginCommand,
    createModel,
    escapeXml,
    expirePending,
    failCommand,
    keyStatus,
    imagePathFor,
    markOffline,
    normalizeSettings,
    renderKeySvg,
    svgToImage,
    textColorForBackground,
};
