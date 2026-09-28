# SOUND_FILES

Place operator alert WAV files in this directory using the naming convention:

- `XX_description.wav`
- `XX` must be exactly two digits and is the only part the application uses.
- Text after the first underscore is descriptive only.
- `.wav` matching is case-insensitive.

Supported IDs:

- `01` Audit OUTER radius entry
- `02` Audit INNER radius entry
- `03` TCAS RA enters any non-`CLEAN` state
- `04` HAZARD enters any abnormal state
- `05` Squawk enters `7500`
- `06` Squawk enters `7600`
- `07` Squawk enters `7700`
- `08` Reserved
- `09` Reserved
- `10` Reserved

Behavior notes:

- Missing files are silent and do not fail the application.
- If multiple files share the same two-digit prefix, DARTS warns in the server console and uses the lexicographically first filename deterministically.
- Playback occurs in the browser-based live map via the existing DARTS HTTP/WebSocket runtime, fetched from `/sounds/XX`.
- Browsers may block audio until the page receives a user interaction.
- Use WAV files only. Short clips under five seconds are recommended to keep transfer, memory, and startup costs modest.
