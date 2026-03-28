# amtap

A terminal app for tapping and storing BPM for tracks playing in Apple Music.

Tap along to the beat, see your consistency in real time, and write the result directly to the file's ID3 tag.

## Requirements

- macOS (uses AppleScript to talk to Apple Music)
- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Installation

Clone the repo and run it directly with uv — no manual environment setup needed:

```sh
git clone https://github.com/robotpistol/amtap.git
cd amtap
uv run amtap
```

uv will create a virtual environment, install dependencies, and launch the app on first run.

## Usage

```
┌─────────────────────────────────────────┐
│  NOW PLAYING                            │
│  Jeep's Blues — Duke Ellington          │
│  Stored BPM: 67                         │
├─────────────────────────────────────────┤
│  TAP BPM                                │
│  Current: 138    Taps: 8                │
├─────────────────────────────────────────┤
│  [SPACE] Tap   [S] Save   [R] Reset     │
│  [Q] Quit                               │
└─────────────────────────────────────────┘
```

| Key     | Action                              |
|---------|-------------------------------------|
| `Space` | Tap the beat                        |
| `S`     | Save tapped BPM to the file's ID3 tag |
| `R`     | Reset tap session and BPM display   |
| `Q`     | Quit                                |

### Tapping BPM

- BPM is displayed after 6 taps.
- Only the last 8 taps are used, so your reading stays responsive as you dial in.
- If you pause for more than 2 seconds between taps, the session resets automatically — the last BPM stays dimmed while you rebuild.
- The BPM value is color-coded by consistency (standard deviation of inter-tap intervals):
  - Green — locked in (< 40ms stddev)
  - Yellow — getting there (40–100ms)
  - Red — inconsistent (> 100ms)

### Saving

Press `S` when you have a reading you're happy with. The app will prompt:

```
Save BPM 138 to "Jeep's Blues"? (y/n)
```

On confirmation, the TBPM tag is written to the file and the stored BPM display updates immediately. Only the TBPM tag is modified — nothing else in the file is touched.

Saving is not available for streaming tracks or tracks with DRM where no local file path is accessible.

## Notes

- Apple Music must be running and playing a track for now-playing info to appear.
- The app polls Apple Music every 2 seconds in a background thread so tap timing is never affected by AppleScript latency.
