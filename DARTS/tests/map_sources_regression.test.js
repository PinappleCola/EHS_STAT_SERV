const assert = require('assert');
const fs = require('fs');
const path = require('path');

const liveMap = fs.readFileSync(path.join(__dirname, '..', 'live_map.html'), 'utf8');

assert.match(liveMap, /ifr_waypoints:\s*emptyFeatureCollection\(\)/);
assert.match(liveMap, /vfr_waypoints:\s*emptyFeatureCollection\(\)/);
assert.match(liveMap, /audit_points:\s*emptyFeatureCollection\(\)/);
assert.match(liveMap, /fetch\(`\$\{HTTP_API\}\/api\/map-data`\)/);
assert.match(liveMap, /parsedData\.map_data_revision/);
assert.match(liveMap, /waypointScoringByName\[entry\.key \|\| entry\.name\]/);
assert.match(liveMap, /hiddenMapSources\[source\]/);
assert.match(liveMap, /hiddenMapSources\.audit_points/);
assert.doesNotMatch(liveMap, /parsedData\.airspace/);

console.log('map_sources_regression: OK');
