#!/usr/bin/env node
'use strict';

const TRAIL_REACQUIRE_GAP_MS = 65000;

function getOrCreateTrailHistory(store, icao, fallbackNowMs = Date.now()) {
    if (!store[icao]) store[icao] = { path: [], lastUpdate: fallbackNowMs, lastPointTime: null };
    return store[icao];
}

function getLastTrailPoint(path) {
    for (let i = path.length - 1; i >= 0; i--) if (!path[i].gapBreak) return path[i];
    return null;
}

function sortTrailPathChronologically(historyObj) {
    if (!historyObj || !Array.isArray(historyObj.path) || historyObj.path.length < 2) return;
    historyObj.path.sort((a, b) => {
        const aTime = Number.isFinite(a?.time) ? a.time : 0;
        const bTime = Number.isFinite(b?.time) ? b.time : 0;
        if (aTime !== bTime) return aTime - bTime;
        const aBreak = !!a?.gapBreak;
        const bBreak = !!b?.gapBreak;
        if (aBreak !== bBreak) return aBreak ? -1 : 1;
        return 0;
    });
}

function normalizeTrailPath(historyObj) {
    if (!historyObj || !Array.isArray(historyObj.path) || historyObj.path.length < 2) return;
    sortTrailPathChronologically(historyObj);
    const compacted = [];
    historyObj.path.forEach((entry) => {
        const last = compacted[compacted.length - 1];
        if (entry.gapBreak) {
            if (last && last.gapBreak && last.time === entry.time && last.markerType === entry.markerType) return;
            compacted.push(entry);
            return;
        }
        if (last && !last.gapBreak && last.time === entry.time && last.lat === entry.lat && last.lon === entry.lon) return;
        compacted.push(entry);
    });
    historyObj.path = compacted;
}

function pruneTrailPathByAge(historyObj) {
    const latest = getLastTrailPoint(historyObj.path);
    historyObj.lastPointTime = latest ? latest.time : null;
}

function ingestTrailRows(store, rows) {
    if (!Array.isArray(rows)) return;
    const touchedIcaos = new Set();
    rows.forEach((row) => {
        if (!Array.isArray(row) || row.length < 2) return;
        const icao = (typeof row[0] === 'string' ? row[0].trim().toUpperCase() : '');
        const eventTime = Number.parseInt(row[1], 10);
        if (!icao || !Number.isFinite(eventTime)) return;
        touchedIcaos.add(icao);
        const historyObj = getOrCreateTrailHistory(store, icao, eventTime);
        if (row[9]) {
            historyObj.path.push({ time: eventTime, gapBreak: true, markerType: row[9] });
            historyObj.lastUpdate = Math.max(historyObj.lastUpdate || 0, eventTime);
            return;
        }
        const lat = Number.parseFloat(row[2]);
        const lon = Number.parseFloat(row[3]);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        historyObj.path.push({ lat, lon, time: eventTime, alt: row[4] });
        historyObj.lastPointTime = Math.max(historyObj.lastPointTime || 0, eventTime);
        historyObj.lastUpdate = Math.max(historyObj.lastUpdate || 0, eventTime);
    });
    touchedIcaos.forEach((icao) => {
        normalizeTrailPath(store[icao]);
        pruneTrailPathByAge(store[icao]);
    });
}

function appendLiveTrailSample(store, sample) {
    if (!sample || !sample.icao || !Number.isFinite(sample.lat) || !Number.isFinite(sample.lon) || !Number.isFinite(sample.time)) return;
    const historyObj = getOrCreateTrailHistory(store, sample.icao, sample.time);
    normalizeTrailPath(historyObj);
    const history = historyObj.path;
    let latestPointIdx = -1;
    for (let i = history.length - 1; i >= 0; i--) {
        if (!history[i].gapBreak) {
            latestPointIdx = i;
            break;
        }
    }
    let previousPointIdx = -1;
    for (let i = history.length - 1; i >= 0; i--) {
        const entry = history[i];
        if (entry.gapBreak) continue;
        if (entry.time <= sample.time) {
            previousPointIdx = i;
            break;
        }
    }
    if (latestPointIdx >= 0) {
        const latestPoint = history[latestPointIdx];
        const hasBreakAfterLatest = history.some((entry, idx) => idx > latestPointIdx && entry.gapBreak && entry.time <= sample.time);
        if (!hasBreakAfterLatest && latestPoint.lat === sample.lat && latestPoint.lon === sample.lon) {
            historyObj.lastUpdate = Math.max(historyObj.lastUpdate || 0, sample.time);
            historyObj.lastPointTime = latestPoint.time;
            pruneTrailPathByAge(historyObj);
            return;
        }
    }
    if (previousPointIdx >= 0) {
        const previousPointTime = history[previousPointIdx].time;
        const hasGapMarkerInRange = history.some((entry, idx) => idx > previousPointIdx && entry.gapBreak && entry.time <= sample.time);
        if (!hasGapMarkerInRange && (sample.time - previousPointTime) > TRAIL_REACQUIRE_GAP_MS) {
            history.push({ time: sample.time, gapBreak: true });
        }
    }
    historyObj.lastUpdate = Math.max(historyObj.lastUpdate || 0, sample.time);
    const hasExactPoint = history.some((entry) => !entry.gapBreak && entry.time === sample.time && entry.lat === sample.lat && entry.lon === sample.lon);
    if (!hasExactPoint) history.push({ lat: sample.lat, lon: sample.lon, time: sample.time, alt: sample.alt });
    normalizeTrailPath(historyObj);
    const latestPoint = getLastTrailPoint(historyObj.path);
    historyObj.lastPointTime = latestPoint ? latestPoint.time : null;
    pruneTrailPathByAge(historyObj);
}

function makePointRow(icao, time, lat, lon, alt = 10000) {
    return [icao, time, lat, lon, alt, null, null, null, null, null];
}

function makeBreakRow(icao, time, markerType) {
    return [icao, time, null, null, null, null, null, null, null, markerType];
}

function countPoints(path) {
    return path.filter((entry) => !entry.gapBreak).length;
}

function countRenderedSegments(path) {
    let count = 0;
    for (let i = 1; i < path.length; i++) {
        if (path[i - 1].gapBreak || path[i].gapBreak) continue;
        count++;
    }
    return count;
}

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

function runTests() {
    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('AAA111', 1000, 1.0, 1.0),
            makePointRow('AAA111', 2000, 2.0, 2.0),
            makeBreakRow('AAA111', 2000, 'gapBreak')
        ]);
        const path = store.AAA111.path;
        assert(path[1].gapBreak === true && path[2].gapBreak !== true, 'same-time break must sort before point');
        assert(countRenderedSegments(path) === 0, 'same-time break marker must prevent A-B bridge');
    }

    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('BBB222', 1000, 1.0, 1.0),
            makeBreakRow('BBB222', 3000, 'gapBreak'),
            makePointRow('BBB222', 3001, 2.0, 2.0)
        ]);
        assert(countRenderedSegments(store.BBB222.path) === 0, 'gap break must prevent bridge');
    }

    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('CCC333', 1000, 1.0, 1.0),
            makeBreakRow('CCC333', 3000, 'jumpBreak'),
            makePointRow('CCC333', 3001, 2.0, 2.0)
        ]);
        assert(countRenderedSegments(store.CCC333.path) === 0, 'jump break must prevent bridge');
    }

    {
        const store = {};
        appendLiveTrailSample(store, { icao: 'DDD444', time: 1000, lat: 1.0, lon: 1.0 });
        appendLiveTrailSample(store, { icao: 'DDD444', time: 2000, lat: 1.0, lon: 1.0 });
        appendLiveTrailSample(store, { icao: 'DDD444', time: 3000, lat: 1.0, lon: 1.0 });
        assert(countPoints(store.DDD444.path) === 1, 'unchanged live coordinates must not create duplicate points');
    }

    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('EEE555', 1000, 1.0, 1.0),
            makePointRow('EEE555', 2000, 2.0, 2.0)
        ]);
        appendLiveTrailSample(store, { icao: 'EEE555', time: 1500, lat: 1.5, lon: 1.5 });
        appendLiveTrailSample(store, { icao: 'EEE555', time: 2500, lat: 2.0, lon: 2.0 });
        const pointTimes = store.EEE555.path.filter((entry) => !entry.gapBreak).map((entry) => entry.time);
        assert(pointTimes.join(',') === '1000,1500,2000', 'hydrated + live points must remain ordered without duplicates');
        assert(countRenderedSegments(store.EEE555.path) === 2, 'hydrated + live points should keep normal joins');
    }

    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('FFF666', 3000, 3.0, 3.0),
            makePointRow('FFF666', 1000, 1.0, 1.0),
            makeBreakRow('FFF666', 2000, 'gapBreak'),
            makePointRow('FFF666', 2000, 2.0, 2.0)
        ]);
        const path = store.FFF666.path;
        assert(path[1].gapBreak === true && path[1].time === 2000, 'out-of-order rows must normalize safely with break before equal-time point');
        assert(countRenderedSegments(path) === 1, 'out-of-order normalized rows must not bridge pre-break to post-break points');
    }

    {
        const store = {};
        ingestTrailRows(store, [
            makePointRow('GGG777', 1000, 1.0, 1.0),
            makePointRow('GGG777', 2000, 1.1, 1.1),
            makePointRow('GGG777', 3000, 1.2, 1.2)
        ]);
        assert(countRenderedSegments(store.GGG777.path) === 2, 'normal consecutive points should still connect');
    }
}

runTests();
console.log('trail_logic_regression.test.js: all tests passed');
