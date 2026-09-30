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

const listeners = {};
const playedSounds = [];
const context = {
    Date,
    Set,
    console,
    document: {
        addEventListener(type, listener) {
            listeners[type] = listener;
        },
    },
    Audio: class {
        constructor(url) {
            this.url = url;
            playedSounds.push(url);
        }
        play() {
            return Promise.resolve();
        }
    },
};
vm.runInNewContext(
    `${liveMap.slice(start, end)}\nglobalThis.soundTestApi = { playSoundEvent, activeSoundPlayers: _activeSoundPlayers };`,
    context
);

context.soundTestApi.playSoundEvent({ event_id: 'session:1', sound_id: '01', url: '/sounds/01' });
assert.deepStrictEqual(playedSounds, []);
listeners.pointerdown({ isTrusted: false });
assert.deepStrictEqual(playedSounds, []);
listeners.pointerdown({ isTrusted: true });
assert.deepStrictEqual(playedSounds, ['/sounds/01']);
assert.strictEqual(context.soundTestApi.activeSoundPlayers.size, 1);

context.soundTestApi.playSoundEvent({ event_id: 'session:1', sound_id: '01', url: '/sounds/01' });
context.soundTestApi.playSoundEvent({ event_id: 'session:2', sound_id: '01', url: '/sounds/01' });
assert.deepStrictEqual(playedSounds, ['/sounds/01', '/sounds/01']);
