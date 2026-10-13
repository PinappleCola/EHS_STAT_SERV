'use strict';

// com.pineapplecola.darts Stream Deck plugin (Node.js, no third-party dependencies).
//
// Stream Deck  <-- WebSocket (SDK) -->  this plugin  <-- HTTP -->  DARTS (localhost:8766)
//   - keyDown          -> POST /api/ui-command {command, request_id}
//   - state (polled)   <- GET  /api/ui-state   (reported by the controlling live map tab)
//
// The live map is authoritative: a key only shows ON/OFF from what the map reports.

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const {
    ACTIONS, TIMING, applySnapshot, beginCommand, createModel, expirePending,
    failCommand, imagePathFor, keyStatus, markOffline, normalizeSettings, renderKeySvg, svgToImage,
} = require('./state');

const DEFAULT_BASE_URL = 'http://127.0.0.1:8766';
const OFFLINE_POLL_MS = 2000;
const MAX_ICON_BYTES = 512 * 1024;
const ICON_MIME = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml',
};

function normalizeBaseUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return DEFAULT_BASE_URL;
    try {
        const url = new URL(value.trim());
        return url.protocol === 'http:' || url.protocol === 'https:' ? url.origin : DEFAULT_BASE_URL;
    } catch (_err) {
        return DEFAULT_BASE_URL;
    }
}

function readIconFile(filePath) {
    const mime = ICON_MIME[path.extname(filePath).toLowerCase()];
    if (!mime) return null;
    const stat = fs.statSync(filePath);
    if (!stat.isFile() || stat.size > MAX_ICON_BYTES) return null;
    return `data:${mime};base64,${fs.readFileSync(filePath).toString('base64')}`;
}

class DartsPlugin {
    constructor(options) {
        this.send = options.send;
        this.fetch = options.fetch || globalThis.fetch;
        this.now = options.now || Date.now;
        this.randomUUID = options.randomUUID || crypto.randomUUID;
        this.setTimer = options.setTimeout || setTimeout;
        this.clearTimer = options.clearTimeout || clearTimeout;
        this.readIcon = options.readIcon || readIconFile;
        this.baseUrl = DEFAULT_BASE_URL;
        this.model = createModel();
        this.contexts = new Map(); // context -> { control, settings, lastImage }
        this.iconCache = new Map();
        this.timer = null;
        this.polling = false;
        this.repoll = false;
        this.running = false;
    }

    start() {
        this.running = true;
        this.renderAll();
        this.requestSync();
    }

    stop() {
        this.running = false;
        this.clearTimer(this.timer);
        this.timer = null;
    }

    log(message) {
        this.send({ event: 'logMessage', payload: { message: `[DARTS] ${message}` } });
    }

    handleDeckMessage(msg) {
        if (!msg || typeof msg !== 'object') return;
        const { event, action, context, payload } = msg;
        switch (event) {
            case 'willAppear': {
                const control = ACTIONS[action];
                if (!control) return;
                this.contexts.set(context, { control, settings: (payload && payload.settings) || {}, lastImage: null });
                this.renderContext(context);
                this.requestSync();
                break;
            }
            case 'willDisappear':
                this.contexts.delete(context);
                break;
            case 'didReceiveSettings': {
                const entry = this.contexts.get(context);
                if (!entry) return;
                entry.settings = (payload && payload.settings) || {};
                entry.lastImage = null;
                this.iconCache.clear();
                this.renderContext(context);
                break;
            }
            case 'didReceiveGlobalSettings':
                this.baseUrl = normalizeBaseUrl(payload && payload.settings && payload.settings.dartsUrl);
                this.requestSync();
                break;
            case 'keyDown':
                return this.pressKey(context);
            case 'systemDidWakeUp':
                this.requestSync();
                break;
            default:
                break;
        }
        return undefined;
    }

    requestSync() {
        if (!this.running) return;
        if (this.polling) {
            this.repoll = true;
            return;
        }
        this.schedulePoll(0);
    }

    schedulePoll(delay) {
        this.clearTimer(this.timer);
        this.timer = this.setTimer(() => { this.timer = null; this.poll(); }, delay);
    }

    async poll() {
        if (this.polling) {
            this.repoll = true;
            return;
        }
        this.polling = true;
        try {
            const res = await this.fetch(`${this.baseUrl}/api/ui-state`, {
                cache: 'no-store', signal: AbortSignal.timeout(TIMING.requestTimeoutMs),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            applySnapshot(this.model, await res.json());
        } catch (_err) {
            markOffline(this.model);
        } finally {
            this.polling = false;
        }
        this.checkPendingTimeout();
        this.renderAll();
        if (!this.running) return;
        if (this.repoll) {
            this.repoll = false;
            this.schedulePoll(0);
        } else if (this.model.pendingCommand) {
            this.schedulePoll(TIMING.pendingPollMs);
        } else {
            this.schedulePoll(this.model.connectionState === 'offline' ? OFFLINE_POLL_MS : TIMING.pollMs);
        }
    }

    checkPendingTimeout() {
        const pending = this.model.pendingCommand;
        if (pending && expirePending(this.model, this.now())) {
            this.log(`${pending.command} (${pending.requestId}) was not confirmed by the live map`);
            this.alertControl(pending.control);
        }
    }

    alertControl(control) {
        for (const [context, entry] of this.contexts) {
            if (entry.control === control) this.send({ event: 'showAlert', context });
        }
    }

    async pressKey(context) {
        const entry = this.contexts.get(context);
        if (!entry) return;
        const begin = beginCommand(this.model, entry.control, this.now(), this.randomUUID);
        if (!begin.ok) {
            if (begin.reason !== 'pending') {
                this.send({ event: 'showAlert', context });
            }
            this.requestSync();
            return;
        }
        this.renderAll();
        try {
            const res = await this.fetch(`${this.baseUrl}/api/ui-command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: begin.command, request_id: begin.requestId }),
                signal: AbortSignal.timeout(TIMING.requestTimeoutMs),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
            if (failCommand(this.model, begin.requestId, this.now())) {
                this.log(`${begin.command} failed: ${err && err.message ? err.message : err}`);
                this.alertControl(entry.control);
            }
        }
        this.renderAll();
        this.requestSync();
    }

    iconFor(iconPath) {
        if (!iconPath) return null;
        if (!this.iconCache.has(iconPath)) {
            let uri = null;
            try {
                uri = this.readIcon(iconPath);
            } catch (err) {
                this.log(`icon override not loaded (${iconPath}): ${err && err.message ? err.message : err}`);
            }
            this.iconCache.set(iconPath, uri);
        }
        return this.iconCache.get(iconPath);
    }

    renderContext(context) {
        const entry = this.contexts.get(context);
        if (!entry) return;
        const status = keyStatus(this.model, entry.control, this.now());
        const settings = normalizeSettings(entry.control, entry.settings);
        let image = this.iconFor(imagePathFor(status, settings));
        if (!image) {
            const icon = this.iconFor(settings.icon);
            image = svgToImage(renderKeySvg(entry.control, status, entry.settings, icon));
        }
        if (image === entry.lastImage) return;
        entry.lastImage = image;
        this.send({ event: 'setImage', context, payload: { image, target: 0 } });
    }

    renderAll() {
        for (const context of this.contexts.keys()) this.renderContext(context);
    }
}

function parseArgs(argv) {
    const args = {};
    for (let i = 0; i < argv.length - 1; i += 1) {
        if (argv[i].startsWith('-')) args[argv[i].slice(1)] = argv[i + 1];
    }
    return args;
}

function main() {
    const args = parseArgs(process.argv.slice(2));
    if (!args.port || !args.pluginUUID || !args.registerEvent) {
        console.error('DARTS plugin must be launched by the Stream Deck app (-port, -pluginUUID, -registerEvent).');
        process.exit(1);
    }
    if (typeof WebSocket === 'undefined' || typeof fetch === 'undefined') {
        console.error('DARTS plugin requires Node.js 22+ (Stream Deck 7.1+ provides Node.js 24).');
        process.exit(1);
    }
    const socket = new WebSocket(`ws://127.0.0.1:${args.port}`);
    const plugin = new DartsPlugin({
        send: (msg) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg)); },
    });
    socket.addEventListener('open', () => {
        socket.send(JSON.stringify({ event: args.registerEvent, uuid: args.pluginUUID }));
        socket.send(JSON.stringify({ event: 'getGlobalSettings', context: args.pluginUUID }));
        plugin.start();
    });
    socket.addEventListener('message', (event) => {
        let msg;
        try {
            msg = JSON.parse(event.data);
        } catch (_err) {
            return;
        }
        Promise.resolve(plugin.handleDeckMessage(msg)).catch((err) => plugin.log(`error: ${err}`));
    });
    socket.addEventListener('close', () => {
        plugin.stop();
        process.exit(0);
    });
}

if (require.main === module) main();

module.exports = { DEFAULT_BASE_URL, DartsPlugin, normalizeBaseUrl, parseArgs, readIconFile };
