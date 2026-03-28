# amtap — Spec

## Overview

A terminal UI app written in Python using Textual that detects the currently playing song in Apple Music, displays its stored BPM from the file's ID3 tag, allows the user to tap a new BPM, and optionally writes the result back to the file.

## Tech Stack

- **Python 3.14+**
- **Textual** for the TUI
- **mutagen** for ID3 tag reading and writing
- **osascript** (via `subprocess`) for Apple Music now-playing detection
- **uv** for dependency management

## Project Structure

```
src/amtap/
    __init__.py
    main.py
pyproject.toml
.python-version
README.md
```

## pyproject.toml Requirements

- `requires-python = ">=3.14"`
- Dependencies: `textual`, `mutagen`
- Entry point: `amtap = "amtap.main:main"` so the app runs via `uv run amtap`
- Hatchling build backend with `packages = ["src/amtap"]`

## Dependencies

```
textual
mutagen
```

No other third-party dependencies. Use stdlib `subprocess` for osascript, `statistics` for stddev calculation, `asyncio` for threading.

## Apple Music Integration

Poll Apple Music every 2 seconds via osascript to detect the currently playing track. Fetch:
- Track name
- Artist
- File path (`POSIX path of location`) — used to read/write the actual file

The osascript call must run in a thread (`asyncio.to_thread`) so it does not block the event loop or affect tap timing.

Use a multi-line AppleScript with newline delimiters (not comma-split) and explicitly convert location to a POSIX path to avoid HFS alias format:

```applescript
tell application "Music"
    set t to current track
    set n to name of t
    set a to artist of t
    try
        set l to POSIX path of (get location of t)
    on error
        set l to ""
    end try
    return n & "\n" & a & "\n" & l
end tell
```

If Apple Music is not running or no track is playing, display a friendly idle state. If the file path is unavailable (e.g. streaming, DRM), display the track name/artist but disable BPM read/write with a clear message.

## Layout

Single-screen Textual app. Suggested layout from top to bottom:

```
┌─────────────────────────────────────────┐
│  NOW PLAYING                            │
│  Track Name — Artist                    │
│  Stored BPM: 142                        │
├─────────────────────────────────────────┤
│  TAP BPM                                │
│  Current: 138    Taps: 8               │
│  consistency color on BPM value         │
├─────────────────────────────────────────┤
│  status messages                        │
├─────────────────────────────────────────┤
│  [SPACE] Tap   [S] Save   [R] Reset     │
│  [Q] Quit                               │
└─────────────────────────────────────────┘
```

## Tap Logic

- **Tap key**: `space`
- Tap timestamps are captured in `on_key` (not the action handler) to minimize event-dispatch latency.
- Each tap records a timestamp. BPM is computed from the average interval across the taps in the current session.
- **Rolling window**: only the last 8 taps are kept. Older taps are dropped as new ones arrive.
- **Minimum taps to display BPM**: 6
- **Displayed BPM**: rounded to the nearest integer.
- **Gap reset**: if the interval between two consecutive taps exceeds 2 seconds, the tap session resets automatically before recording the new tap. The last displayed BPM is preserved (shown dimmed) until the new session produces a fresh reading.
- **Manual reset** (`R`): clears the tap session and the displayed BPM entirely.

## Consistency Indicator

Compute the standard deviation of inter-tap intervals (in milliseconds) across the current tap session. Map stddev to a color for the displayed current BPM value:

| Stddev (ms) | Color  | Meaning        |
|-------------|--------|----------------|
| < 40ms      | Green  | Locked in      |
| 40–100ms    | Yellow | Getting there  |
| > 100ms     | Red    | Inconsistent   |

Show color only once there are at least 3 taps. Before that, display BPM in neutral color with no indicator.

## Saving BPM

- Press `S` to initiate a save.
- App displays a confirmation prompt: `Save BPM 138 to "[Track Name]"? (y/n)`
- All other key bindings are suppressed while the prompt is shown.
- On `y`: write the TBPM tag using mutagen, refresh the stored BPM display.
- On `n` or `Escape`: dismiss and return to normal state.
- If no file path is available, `S` is a no-op with a status message: `Cannot write: file path unavailable`.
- If no BPM has been tapped yet, `S` is a no-op with a status message: `No BPM tapped yet`.

## ID3 Write Implementation

```python
from mutagen.id3 import ID3, ID3NoHeaderError, TBPM

try:
    tags = ID3(filepath)
except ID3NoHeaderError:
    tags = ID3()

tags["TBPM"] = TBPM(encoding=3, text=[str(bpm)])
tags.save(filepath)
```

Handle `mutagen.id3.ID3NoHeaderError` gracefully by initializing fresh tags.

## Error Handling

- Apple Music not running → show idle state, keep polling
- No track playing → show idle state
- File path unavailable (streaming/DRM) → show track info, disable save
- mutagen write failure → show error message in status bar, do not crash
- osascript timeout or error → treat as no track playing

## What the App Should NOT Do

- Do not attempt to control Apple Music playback
- Do not fetch BPM from any external API or service — stored tag is the only source of truth
- Do not modify any tag other than TBPM
