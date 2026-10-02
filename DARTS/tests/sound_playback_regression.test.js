#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');
const start = liveMap.indexOf('        const _playedSoundEventIds = new Set();');
const end = liveMap.indexOf('        function toggleAuditModal()', start);
assert.notStrictEqual(start, -1);
assert.notStrictEqual(end, -1);

const httpApiMatch = liveMap.match(/const HTTP_API = '([^']+)';/);
assert.ok(httpApiMatch, 'HTTP_API constant not found in live_map.html');
const HTTP_API = httpApiMatch[1];
assert.strictEqual(HTTP_API, 'http://localhost:8766');
const SOUND_01 = `${HTTP_API}/sounds/01`;

const listeners = {};
const playedSounds = [];
const warnings = [];
const context = {
    HTTP_API,
    Date,
    Set,
    console: {
        warn(...args) {
            warnings.push(args.map(String).join(' '));
        },
    },
    document: {
        addEventListener(type, listener) {
            listeners[type] = listener;
        },
    },
    Audio: class {
        constructor(url) {
            this.url = url;
            this.listeners = {};
            playedSounds.push(url);
        }
        addEventListener(type, listener) {
            this.listeners[type] = listener;
        }
        play() {
            if (this.url.endsWith('/sounds/99')) {
                const error = new Error('not found');
                error.name = 'NotSupportedError';
                return Promise.reject(error);
            }
            return Promise.resolve();
        }
    },
};
vm.runInNewContext(
    `${liveMap.slice(start, end)}\nglobalThis.soundTestApi = { playSoundEvent, resolveSoundUrl, activeSoundPlayers: _activeSoundPlayers };`,
    context
);

context.soundTestApi.playSoundEvent({ event_id: 'session:1', sound_id: '01', url: '/sounds/01' });
assert.deepStrictEqual(playedSounds, []);
listeners.pointerdown({ isTrusted: false });
assert.deepStrictEqual(playedSounds, []);
listeners.pointerdown({ isTrusted: true });
assert.deepStrictEqual(playedSounds, [SOUND_01]);
assert.strictEqual(context.soundTestApi.activeSoundPlayers.size, 1);

context.soundTestApi.playSoundEvent({ event_id: 'session:1', sound_id: '01', url: '/sounds/01' });
context.soundTestApi.playSoundEvent({ event_id: 'session:2', sound_id: '01', url: '/sounds/01' });
assert.deepStrictEqual(playedSounds, [SOUND_01, SOUND_01]);

// Relative URLs always resolve against the fixed HTTP API server; absolute URLs are untouched.
assert.strictEqual(context.soundTestApi.resolveSoundUrl('/sounds/07'), `${HTTP_API}/sounds/07`);
assert.strictEqual(context.soundTestApi.resolveSoundUrl('/sounds/07.wav'), `${HTTP_API}/sounds/07.wav`);
assert.strictEqual(context.soundTestApi.resolveSoundUrl(`${HTTP_API}/sounds/07`), `${HTTP_API}/sounds/07`);

// Fallback URL (no url in event) is also absolute.
context.soundTestApi.playSoundEvent({ event_id: 'session:3', sound_id: '2' });
assert.strictEqual(playedSounds[playedSounds.length - 1], `${HTTP_API}/sounds/02`);

// Failures log the absolute URL that could not be fetched.
context.soundTestApi.playSoundEvent({ event_id: 'session:4', sound_id: '99', url: '/sounds/99' });
setImmediate(() => {
    assert.ok(
        warnings.some((w) => w.includes(`${HTTP_API}/sounds/99`)),
        `expected a warning naming the failed URL, got: ${JSON.stringify(warnings)}`
    );
    console.log('sound_playback_regression: OK');
});
