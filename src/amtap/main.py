from __future__ import annotations

import asyncio
import statistics
import subprocess
import time
from dataclasses import dataclass, field

from mutagen.id3 import ID3, TBPM, ID3NoHeaderError
from textual.app import App, ComposeResult
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import Footer, Label, Static

# ---------------------------------------------------------------------------
# Apple Music helpers
# ---------------------------------------------------------------------------

@dataclass
class TrackInfo:
    name: str
    artist: str
    path: str | None  # None = streaming / DRM / unavailable
    stored_bpm: int | None  # None = tag missing or file unavailable


def _read_stored_bpm(filepath: str) -> int | None:
    try:
        tags = ID3(filepath)
        tbpm = tags.get("TBPM")
        if tbpm:
            return int(tbpm.text[0])
    except (ID3NoHeaderError, Exception):
        pass
    return None


def write_bpm(filepath: str, bpm: int) -> None:
    try:
        tags = ID3(filepath)
    except ID3NoHeaderError:
        tags = ID3()
    tags["TBPM"] = TBPM(encoding=3, text=[str(bpm)])
    tags.save(filepath)


def poll_apple_music() -> TrackInfo | None:
    """Return TrackInfo for the current track, or None if nothing is playing."""
    script = """\
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
end tell"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    parts = raw.split("\n", 2)
    if len(parts) < 2:
        return None

    name = parts[0]
    artist = parts[1]
    raw_path = parts[2].strip() if len(parts) > 2 else ""
    path: str | None = raw_path if raw_path else None

    stored_bpm: int | None = _read_stored_bpm(path) if path else None
    return TrackInfo(name=name, artist=artist, path=path, stored_bpm=stored_bpm)


# ---------------------------------------------------------------------------
# Tap session
# ---------------------------------------------------------------------------

@dataclass
class TapSession:
    taps: list[float] = field(default_factory=list)

    MAX_TAPS = 8

    def tap(self, t: float) -> None:
        self.taps.append(t)
        if len(self.taps) > self.MAX_TAPS:
            self.taps.pop(0)

    def reset(self) -> None:
        self.taps.clear()

    @property
    def count(self) -> int:
        return len(self.taps)

    def _intervals(self) -> list[float]:
        return [self.taps[i + 1] - self.taps[i] for i in range(len(self.taps) - 1)]

    @property
    def bpm(self) -> float | None:
        if len(self.taps) < 6:
            return None
        return 60.0 / statistics.mean(self._intervals())

    @property
    def stddev_ms(self) -> float | None:
        if len(self.taps) < 3:
            return None
        return statistics.stdev(self._intervals()) * 1000


# ---------------------------------------------------------------------------
# Textual widgets
# ---------------------------------------------------------------------------

class NowPlayingPane(Static):
    DEFAULT_CSS = """
    NowPlayingPane {
        border: solid $primary;
        padding: 0 1;
        height: auto;
    }
    NowPlayingPane .section-title {
        color: $text-muted;
        text-style: bold;
    }
    """

    track: reactive[TrackInfo | None] = reactive(None, layout=True)

    def compose(self) -> ComposeResult:
        yield Label("NOW PLAYING", classes="section-title")
        yield Label("—", id="track-line")
        yield Label("Stored BPM: —", id="bpm-line")

    def watch_track(self, info: TrackInfo | None) -> None:
        track_label = self.query_one("#track-line", Label)
        bpm_label = self.query_one("#bpm-line", Label)

        if info is None:
            track_label.update("No track playing")
            bpm_label.update("Stored BPM: —")
            return

        track_label.update(f"{info.name}  —  {info.artist}")

        if info.path is None:
            bpm_label.update("Stored BPM: — (file path unavailable)")
        elif info.stored_bpm is None:
            bpm_label.update("Stored BPM: — (tag not set)")
        else:
            bpm_label.update(f"Stored BPM: {info.stored_bpm}")


class TapPane(Static):
    DEFAULT_CSS = """
    TapPane {
        border: solid $primary;
        padding: 0 1;
        height: auto;
    }
    TapPane .section-title {
        color: $text-muted;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("TAP BPM", classes="section-title")
        yield Label("Current: —    Taps: 0", id="tap-status")

    def update_session(
        self, session: TapSession, fallback_bpm: int | None = None
    ) -> None:
        label = self.query_one("#tap-status", Label)
        n = session.count

        bpm = session.bpm
        if bpm is None:
            if fallback_bpm is not None:
                label.update(f"Current: [dim]{fallback_bpm}[/dim]    Taps: {n}")
            else:
                label.update(f"Current: —    Taps: {n}")
            return

        bpm_str = str(round(bpm))
        stddev = session.stddev_ms

        if stddev is None:
            text = f"Current: {bpm_str}    Taps: {n}"
        elif stddev < 40:
            text = (
                f"Current: [$success]{bpm_str}[/$success]"
                f"    Taps: {n}    [dim]● locked in[/dim]"
            )
        elif stddev < 100:
            text = (
                f"Current: [$warning]{bpm_str}[/$warning]"
                f"    Taps: {n}    [dim]● getting there[/dim]"
            )
        else:
            text = (
                f"Current: [$error]{bpm_str}[/$error]"
                f"    Taps: {n}    [dim]● inconsistent[/dim]"
            )
        label.update(text)


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="status-msg")

    def set_message(self, msg: str, style: str = "") -> None:
        label = self.query_one("#status-msg", Label)
        label.update(f"[{style}]{msg}[/{style}]" if style else msg)

    def clear(self) -> None:
        self.query_one("#status-msg", Label).update("")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class AmtapApp(App):
    BINDINGS = [
        ("space", "tap", "Tap"),
        ("s", "save", "Save"),
        ("r", "reset", "Reset"),
        ("q", "quit", "Quit"),
    ]

    CSS = """
    Screen {
        layout: vertical;
        padding: 1 2;
    }
    NowPlayingPane {
        margin-bottom: 1;
    }
    TapPane {
        margin-bottom: 1;
    }
    """

    current_track: reactive[TrackInfo | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._session = TapSession()
        self._pending_tap_t: float | None = None
        self._last_bpm: int | None = None
        self._confirming = False

    def compose(self) -> ComposeResult:
        yield NowPlayingPane(id="now-playing")
        yield TapPane(id="tap-pane")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2, self._poll)
        self.call_after_refresh(self._poll)

    async def _poll(self) -> None:
        track = await asyncio.to_thread(poll_apple_music)
        self.current_track = track
        self.query_one("#now-playing", NowPlayingPane).track = track

    def _do_reset(self) -> None:
        self._session.reset()
        tap_pane = self.query_one("#tap-pane", TapPane)
        tap_pane.update_session(self._session, self._last_bpm)

    def on_key(self, event: Key) -> None:
        if self._confirming:
            event.prevent_default()
            event.stop()
            if event.key == "y":
                self._confirm_save()
            elif event.key in ("n", "escape"):
                self._cancel_save()
            return

        if event.key == "space":
            self._pending_tap_t = time.monotonic()

    def action_tap(self) -> None:
        if self._confirming:
            return
        t = self._pending_tap_t if self._pending_tap_t is not None else time.monotonic()
        self._pending_tap_t = None

        # If the gap from the last tap exceeds 2 seconds, start a fresh session
        # but keep displaying the last good BPM until the new one is established.
        if self._session.taps and (t - self._session.taps[-1]) > 2.0:
            self._session.reset()

        self._session.tap(t)

        if self._session.bpm is not None:
            self._last_bpm = round(self._session.bpm)

        tap_pane = self.query_one("#tap-pane", TapPane)
        tap_pane.update_session(self._session, self._last_bpm)

    def action_save(self) -> None:
        if self._confirming:
            return

        track = self.current_track
        if track is None or track.path is None:
            self.query_one("#status-bar", StatusBar).set_message(
                "Cannot write: file path unavailable", "dim"
            )
            return

        bpm = self._session.bpm
        if bpm is None:
            self.query_one("#status-bar", StatusBar).set_message(
                "No BPM tapped yet", "dim"
            )
            return

        bpm_int = round(bpm)
        self._confirming = True
        self.query_one("#status-bar", StatusBar).set_message(
            f'Save BPM {bpm_int} to "{track.name}"? (y/n)'
        )

    def _confirm_save(self) -> None:
        self._confirming = False
        track = self.current_track
        bpm = self._session.bpm
        if track is None or track.path is None or bpm is None:
            self.query_one("#status-bar", StatusBar).clear()
            return

        bpm_int = round(bpm)
        status = self.query_one("#status-bar", StatusBar)
        try:
            write_bpm(track.path, bpm_int)
            # Update the stored BPM in the now-playing pane immediately
            track.stored_bpm = bpm_int
            self.query_one("#now-playing", NowPlayingPane).track = track
            status.set_message(f"Saved BPM {bpm_int} to \"{track.name}\"", "success")
        except Exception as e:
            status.set_message(f"Write failed: {e}", "error")

    def _cancel_save(self) -> None:
        self._confirming = False
        self.query_one("#status-bar", StatusBar).clear()

    def action_reset(self) -> None:
        if self._confirming:
            self._cancel_save()
            return
        self._last_bpm = None
        self._do_reset()


def main() -> None:
    AmtapApp().run()


if __name__ == "__main__":
    main()
