# DARTS Stream Deck Button Specification & Design Standard

## 1. Overview & Purpose

This document establishes the repository-backed design standard and architectural specification for Stream Deck buttons in the DARTS system (`PinappleCola/EHS_STAT_SERV`).

The goal is to provide a clean, predictable, and calm user experience for hardware keys while preserving absolute correctness against the live system. This specification serves as the baseline for existing buttons (`MAP`, `IFR`, `VFR`) and future button additions, allowing future Copilot sessions and contributors to continue development without historical ambiguity.

---

## 2. Core Architecture & Authority Model

### 2.1 The Live Map as Source of Truth
- **Authoritative Client**: In the current architecture, ribbon toggles (`MAP`, `IFR`, `VFR`) control client-side browser display state. The live map web client (`DARTS/live_map.html`) is the authoritative source of truth.
- **No Optimistic Guessing**: The Stream Deck plugin **never guesses** the outcome of a toggle or assumes immediate success. It strictly reflects state reported by the controlling live map.
- **Communication Flow**:
  1. Stream Deck button press triggers `POST /api/ui-command` with `{ command, request_id }`.
  2. DARTS HTTP API server (`darts.py:DARTSAPIHandler`) forwards the command over WebSocket (`:8765`) to connected browser map instances.
  3. The active/controlling map executes the toggle and broadcasts a `ui_state` snapshot back to the server, echoing the matching `request_id`.
  4. The plugin polls `GET /api/ui-state` (1000 ms normally, 250 ms while pending) and reconciles against the echoed `request_id`.

```
Stream Deck App ⇄ Native Plugin (Go) ──HTTP POST /api/ui-command──▶ DARTS (:8766) ──WS (:8765)──▶ Live Map Tab
                                      ◀──HTTP GET /api/ui-state─── DARTS (:8766) ◀──WS ui_state───┘
```

### 2.2 Background Browser Tolerance
- **Browser does NOT need to be frontmost**: The live map page does **not** need to be the active or frontmost window on the screen. It can be running in the background behind other applications (e.g. flight simulators, ATC displays, or development tools).
- **Connectivity Requirement**: The browser must remain open and connected.
- **Background Throttling**: Some browsers throttle background timers or suspend inactive tabs. The system handles this gracefully:
  - As long as the WebSocket connection remains open and heartbeats continue, buttons function normally.
  - If a background tab is throttled and misses reports for > 6 seconds, `GET /api/ui-state` reports `connectionState: "stale"`, which the plugin displays cleanly.

---

## 3. Button Archetype: "Confirmed Toggle"

The current MAP, IFR, and VFR keys follow the **Confirmed Toggle** archetype.

### 3.1 Interaction & State Machine

| State | Status Text | Default Background | Default Text | Behavior & Meaning |
|---|---|---|---|---|
| **ON** | `ON` | `#15803D` (Green) | `#FFFFFF` (White) | Feature is confirmed enabled by live map. |
| **OFF** | `OFF` | `#B91C1C` (Red) | `#FFFFFF` (White) | Feature is confirmed disabled by live map. |
| **PENDING** *(internal)* | Last confirmed (`ON`/`OFF`) | Last confirmed color | Last confirmed text | Command dispatched; plugin awaits echo of `request_id`. Routine `WAIT`/amber flash is **hidden**. |
| **ERROR** | `ERROR` | `#B45309` (Amber) | `#FFFFFF` (White) | Command failed (HTTP error) or confirmation timed out (3000 ms). Flashes Stream Deck alert (`showAlert`). Held for 1500 ms before returning to live state. |
| **OFFLINE** | `OFFLINE` | `#CBD5E1` (Slate 300) | `#0F172A` (Dark slate) | DARTS server is unreachable. Calm, light neutral appearance. |
| **NO MAP** | `NO MAP` | `#475569` (Slate 600) | `#FFFFFF` (White) | DARTS server reachable, but no browser map tab is open. |
| **STALE** | `STALE` | `#475569` (Slate 600) | `#FFFFFF` (White) | Map tab is open but hasn't reported for > 6000 ms (e.g. frozen/suspended tab). |

### 3.2 Visual Polish Principles

1. **Suppression of Routine WAIT Graphic**:
   - Ordinary toggle operations take between 20 ms and 200 ms to confirm.
   - Showing an amber `WAIT` graphic for normal toggles creates visually noisy UI flickering.
   - **Standard**: When a button is pressed, the key continues showing its **last confirmed state** (`ON` or `OFF`) until the map confirms the new state. Internally, the plugin tracks `pendingCommand` and accelerates polling to 250 ms.
2. **Calm Rapid-Press Feedback (No False Alarms)**:
   - When a command is already pending, rapid subsequent presses of the same or another button are safely ignored to avoid sending conflicting commands.
   - **Standard**: The Stream Deck exclamation mark alert (`showAlert`) is **suppressed** for busy/pending presses. The key stays calm and does not flash an alarm for normal double-taps.
   - `showAlert` is reserved exclusively for genuine errors: network failure, HTTP 5xx/4xx errors, or confirmation timeout after 3 seconds.
3. **Calm Disconnected/Offline Graphic**:
   - When DARTS is stopped or offline, keys display a calm, light neutral background (`#CBD5E1`) with high-contrast dark text (`#0F172A`), rather than an alarming dark or emergency look.
   - The graphic is clearly distinct from `ON` (green) and `OFF` (red).

### 3.3 Timing Constants
- **`pollInterval`**: 1000 ms (normal background polling)
- **`pendingPollInterval`**: 250 ms (accelerated polling during pending command)
- **`requestTimeout`**: 1500 ms (HTTP request timeout)
- **`confirmTimeout`**: 3000 ms (maximum wait for map echo before transitioning to `ERROR`)
- **`errorHoldDuration`**: 1500 ms (duration to display `ERROR` before returning to live state)

---

## 4. Visual Contract & Icon Conventions

### 4.1 Rendering Contract (SVG)
- **Canvas Dimensions**: 144×144 px (Elgato Stream Deck standard resolution).
- **Background**: Rounded rectangle (`rx="16"`, `ry="16"`).
- **Label**: Centered text (top: `y="52"` without icon, `y="108"` with icon). Automatically scales down if length exceeds 3 characters, truncated at 10 characters.
- **Status**: Centered text (bottom: `y="118"` without icon, `y="132"` with icon, `font-size="22"` or `"16"`).
- **Contrast Adaptation**: Text fill is dynamically computed based on background relative luminance:
  - Light backgrounds (luminance > 160): `#0F172A` (dark text).
  - Dark / saturated backgrounds (luminance ≤ 160): `#FFFFFF` (white text).
- **SVG Data URI**: Rendered dynamically into `data:image/svg+xml;charset=utf8,<svg>...`.

### 4.2 Replaceable Artwork & Custom Icons
- **Decoupled from Logic**: Icons and visual assets are strictly cosmetic overlays. Swapping or replacing image assets does not alter button state logic or command handling.
- **Icon Placement**:
  - Centered at `x="44"`, `y="18"`, `width="56"`, `height="56"`.
  - Configurable per-key via Property Inspector (`ui/settings.html`), supporting absolute path or base64 data URI.
- **Static Assets (`imgs/`)**:
  - `key.png` (72×72) and `key@2x.png` (144×144): Default fallback graphic used by Stream Deck prior to plugin connection, aligned with `#CBD5E1` neutral offline style.
  - `action.png` / `action@2x.png`: Action palette icons.
  - `plugin.png` / `plugin@2x.png`: Plugin catalog icon.

---

## 5. Recipe: How to Add a Future Button

To add a new button following the Confirmed Toggle archetype, follow these steps:

### Step 1: Ensure Backend Endpoint Exists
- Verify that `DARTS/darts.py` supports the command in `POST /api/ui-command` and the corresponding state field in `GET /api/ui-state`.
- Verify that `DARTS/live_map.html` (or relevant frontend) applies the command and broadcasts the updated state.

### Step 2: Register in Go Plugin (`DARTS/streamdeck/plugin/src_go/state.go`)
1. Add the control configuration to `Controls`:
   ```go
   "new_btn": {
       Command:  "toggle_new_btn",
       StateKey: "newBtnEnabled",
       Label:    "NEW",
   },
   ```
2. Map the action UUID to the control in `Actions`:
   ```go
   "com.pineapplecola.darts.new_btn": "new_btn",
   ```
3. Update `UiStateSnapshot` struct and `ApplySnapshot` if a new JSON field is introduced.

### Step 3: Register in Reference JS (`DARTS/streamdeck/plugin/com.pineapplecola.darts.sdPlugin/bin/state.js`)
Keep the reference JavaScript implementation in exact parity:
```javascript
CONTROLS: {
    new_btn: { command: 'toggle_new_btn', stateKey: 'newBtnEnabled', label: 'NEW' },
    ...
},
ACTIONS: {
    'com.pineapplecola.darts.new_btn': 'new_btn',
    ...
}
```

### Step 4: Add Action to `manifest.json`
Add the new action definition to `manifest.json`:
```json
{
  "UUID": "com.pineapplecola.darts.new_btn",
  "Name": "NEW toggle",
  "Tooltip": "Toggle NEW feature on the live map.",
  "Icon": "imgs/action",
  "Controllers": ["Keypad"],
  "SupportedInMultiActions": false,
  "UserTitleEnabled": false,
  "States": [
    {
      "Image": "imgs/key",
      "ShowTitle": false
    }
  ]
}
```

### Step 5: Update Property Inspector (`ui/settings.html`)
Add the default label for the action in `DEFAULT_LABELS`:
```javascript
const DEFAULT_LABELS = {
    ...
    'com.pineapplecola.darts.new_btn': 'NEW',
};
```

### Step 6: Add & Run Regression Tests
- Add unit and scenario assertions in:
  - `DARTS/streamdeck/plugin/src_go/state_test.go`
  - `DARTS/streamdeck/plugin/src_go/plugin_test.go`
  - `DARTS/tests/streamdeck_plugin_regression.test.js`
- Run `npm test` inside `DARTS/streamdeck/plugin/` to ensure all tests pass.

### Step 7: Build Standalone Binaries
Rebuild the Windows and macOS executables:
```bash
node build.js
```
Package the updated `.streamDeckPlugin` artifact into `dist/`.

---

## 6. Future Button Archetypes (Roadmap)

While the Confirmed Toggle pattern covers MAP, IFR, and VFR, future extensions may introduce new archetypes:

1. **Momentary / Action Buttons**:
   - Fire-and-forget commands (e.g. "Recenter Map", "Clear Trails", "Mute Audio").
   - No `ON`/`OFF` status; brief visual acknowledgement on press (e.g. 500 ms flash), then return to default ready state.
2. **Multi-State Cycle Buttons**:
   - Step through a finite set of options (e.g. basemap style: Default → Dark → Satellite → Terrain).
   - Display current active state name and icon.
3. **Telemetry & Readout Displays (Headless Operation)**:
   - Status-only or hybrid readout buttons displaying real-time values (e.g. active aircraft count, frame rate, receiver health).
   - Driven directly by DARTS server APIs, functional even without any browser window open.
