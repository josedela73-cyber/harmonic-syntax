#!/usr/bin/env python3
"""Explore a completed synthetic task run through plain text and optional tones.

No sounds play automatically. Uses Python's standard library. Speech is
provided by the user's screen reader, not by a bundled speech service.
"""

from __future__ import annotations

import argparse
from array import array
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave

import harmonic as hs

SAMPLE_RATE = 22050
HELP = ("Commands: next or n; previous or b; show or s; play or p; stop; "
        "first; last; help or h; quit or q. Press Enter after each command. "
        "An empty command repeats the current stage. Nothing plays automatically.")


def stages(execution: dict) -> list[dict]:
    """Construct stable, plain-text descriptions from actual completed events."""
    frames = []
    for event in execution["events"]:
        records = [r for r in execution["operations"] if r["step"] == event["step"]]
        title = f"Stage {event['step'] + 1}. "
        title += ("Rest." if not records else
                  f"{len(records)} independent tasks in one group." if len(records) > 1 else "One task.")
        lines = [title, "Stage status: " + ("failed" if event["status"] == "error" else "completed") + "."]
        for record in records:
            inputs = []
            for name, value in zip(record["inputs"], record["input_values"]):
                detail = str(value["count"]) + " numbers" if isinstance(value, dict) else str(value)
                inputs.append(name + " equals " + detail)
            description = f"Task {record['note']}: {record['task']}. Inputs: " + "; ".join(inputs) + ". "
            if record["status"] == "error":
                description += "Failed: " + record["error"] + "."
            else:
                description += "Computed result: " + str(record["value"]) + "."
                if record["output"]:
                    description += (" Published as " + record["output"] + "." if event["status"] == "ok"
                                    else " Not published because a task in this stage failed.")
            lines.append(description)
        if event["status"] == "error":
            lines.append("No outputs from this stage were published. Later stages did not run.")
        frames.append({"step": event["step"], "records": records, "status": event["status"],
                       "text": "\n".join(lines)})
    return frames


def summary(execution: dict) -> str:
    state = "finished" if execution["status"] == "ok" else "stopped after a task failure"
    return (f"Run {state}. {execution['completed_events']} of {execution['planned_events']} stages ran. "
            f"{len(execution['operations'])} task operations ran. "
            "A finished run does not establish that its calculations match the intended problem.")


def transcript(execution: dict) -> str:
    parts = [summary(execution)] + [f["text"] for f in stages(execution)]
    if execution["outputs"]:
        parts.append("Published results:\n" + "\n".join(f"{name}: {value}" for name, value in execution["outputs"].items()))
    return "\n\n".join(parts) + "\n"


def _tone(frequencies: list[float], duration: float, volume: float) -> list[int]:
    count = round(duration * SAMPLE_RATE)
    if not frequencies:
        return [0] * count
    ramp = max(1, round(.012 * SAMPLE_RATE))
    samples = []
    for index in range(count):
        envelope = min(1.0, index / ramp, (count - 1 - index) / ramp)
        amplitude = sum(math.sin(2 * math.pi * frequency * index / SAMPLE_RATE) for frequency in frequencies) / len(frequencies)
        samples.append(round(32767 * volume * envelope * amplitude))
    return samples


def _frequency(note: str) -> float:
    frequency = 440 * 2 ** ((hs.pitch(note) - 69) / 12)
    # Octave folding keeps very high/low score notes within this tone palette.
    while frequency < 220:
        frequency *= 2
    while frequency > 880:
        frequency /= 2
    return frequency


def stage_samples(frame: dict, *, volume: float = .15, seconds: float = .35) -> list[int]:
    if type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError("Volume must be from zero to one")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not .1 <= seconds <= 2:
        raise ValueError("Stage sound duration must be from 0.1 to 2 seconds")
    frequencies = [_frequency(r["note"]) for r in frame["records"]]
    samples = _tone(frequencies, seconds, volume)
    if frame["status"] == "error":
        # A dedicated alert is triggered by run status, never musical dissonance.
        samples += _tone([], .08, volume) + _tone([740], .12, volume)
        samples += _tone([], .06, volume) + _tone([370], .18, volume)
    return samples


def write_wav(path: Path, samples: list[int]) -> None:
    payload = array("h", samples)
    if sys.byteorder != "little":
        payload.byteswap()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(payload.tobytes())


def export(execution: dict, destination: Path, *, volume: float = .15, seconds: float = .35) -> list[Path]:
    frames = stages(execution)
    destination.mkdir(parents=True, exist_ok=True)
    paths, overview = [], []
    for index, frame in enumerate(frames, 1):
        samples = stage_samples(frame, volume=volume, seconds=seconds)
        path = destination / f"stage-{index:02}.wav"
        write_wav(path, samples)
        paths.append(path)
        overview += samples + _tone([], .16, volume)
    path = destination / "overview.wav"
    write_wav(path, overview)
    paths.append(path)
    path = destination / "transcript.txt"
    path.write_text(transcript(execution), encoding="utf-8")
    paths.append(path)
    return paths


class Player:
    """Play only a requested generated cue; stop only this instance's playback."""

    def __init__(self):
        self.process = None
        self.windows = None

    def play(self, path: Path) -> str:
        self.stop()
        if sys.platform == "win32":
            import winsound
            self.windows = winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return "Playing the current stage. Type stop to stop."
        candidates = ("afplay",) if sys.platform == "darwin" else ("paplay", "aplay")
        executable = next((found for name in candidates if (found := shutil.which(name))), None)
        if executable is None:
            return "No supported audio player was found. Text navigation still works. Use --audio-dir to export WAV files."
        self.process = subprocess.Popen([executable, str(path)], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Playing the current stage. Type stop to stop."

    def stop(self) -> None:
        if self.windows is not None:
            self.windows.PlaySound(None, 0)
            self.windows = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=.5)
            self.process = None


def explore(execution: dict, *, text_only: bool = False, volume: float = .15,
            seconds: float = .35, read=input, say=print) -> None:
    frames = stages(execution)
    if not frames:
        say("No completed stages to inspect.")
        return
    index = 0
    player = Player()
    say(summary(execution))
    say(HELP)
    say(frames[index]["text"])
    with tempfile.TemporaryDirectory(prefix="harmonic-cues-") as folder:
        try:
            while True:
                try:
                    command = read("Command: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    say("Leaving the trace explorer.")
                    break
                if command in ("quit", "q"):
                    break
                if command == "stop":
                    player.stop(); say("Playback stopped."); continue
                if command in ("play", "p"):
                    if text_only:
                        say("Sound is disabled by --text-only. The current stage is available as text.")
                        continue
                    try:
                        path = Path(folder) / "current-stage.wav"
                        player.stop()
                        write_wav(path, stage_samples(frames[index], volume=volume, seconds=seconds))
                        say(player.play(path))
                    except (OSError, RuntimeError) as error:
                        say("Audio unavailable: " + str(error) + ". Text navigation remains available.")
                    continue
                if command in ("help", "h"):
                    say(HELP); continue
                if command in ("next", "n"):
                    if index == len(frames) - 1:
                        say("This is the last completed stage.")
                    index = min(index + 1, len(frames) - 1)
                elif command in ("previous", "b"):
                    if index == 0:
                        say("This is the first stage.")
                    index = max(0, index - 1)
                elif command == "first":
                    index = 0
                elif command == "last":
                    index = len(frames) - 1
                elif command not in ("show", "s", ""):
                    say("Unknown command. Type help for commands.")
                    continue
                player.stop()
                say(frames[index]["text"])
        finally:
            player.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    parser.add_argument("--transcript", action="store_true", help="print the complete text trace without interaction")
    parser.add_argument("--audio-dir", type=Path, help="export stage WAVs, an overview, and transcript; never autoplay")
    parser.add_argument("--text-only", action="store_true", help="disable sounds in the interactive explorer")
    parser.add_argument("--volume", type=float, default=.15, help="cue amplitude 0..1; does not change system volume")
    parser.add_argument("--seconds", type=float, default=.35, help="presentation duration per stage, 0.1..2 seconds")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.volume) or not 0 <= args.volume <= 1:
            raise ValueError("Volume must be from zero to one")
        if not math.isfinite(args.seconds) or not .1 <= args.seconds <= 2:
            raise ValueError("Stage sound duration must be from 0.1 to 2 seconds")
        if args.text_only and args.audio_dir:
            raise ValueError("Use either --text-only or --audio-dir")
        with args.score.open(encoding="utf-8") as handle:
            source = handle.read(hs.MAX_SOURCE + 1)
        execution = hs.run(hs.compile_score(source))
        if args.audio_dir:
            paths = export(execution, args.audio_dir, volume=args.volume, seconds=args.seconds)
            print(f"Exported {len(paths)} files. No audio was played.")
            print(transcript(execution))
        elif args.transcript:
            print(transcript(execution))
        else:
            explore(execution, text_only=args.text_only, volume=args.volume, seconds=args.seconds)
    except (ValueError, OSError, UnicodeError) as error:
        print("Unable to explore score: " + str(error), file=sys.stderr)
        return 2
    return 0 if execution["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
