# Validation for the 0.3.0 source candidate

Prepared October 25, 2026. Run in an isolated Linux workspace on Python 3.12.

- 73 automated behavioral tests passed; zero failures, errors, or skipped tests.
- Includes 53 execution/dependency tests and 20 audio-explorer tests.
- Text navigation, no automatic playback, explicit play/stop, failure
  publication, input values, and WAV generation were checked.
- Generated completed-run and failed-run samples have valid mono, 16-bit,
  22050 Hz PCM WAV headers and matching text transcripts.
- Windows/macOS playback integration was tested through mocks; physical-device
  playback, hearing quality, and assistive-technology compatibility were not
  evaluated.
- No participant usability study or independent AI coding-accuracy trial was
  conducted for this accessibility prototype.

Reproduce the automated suite from the project root:

```console
python -m unittest -v
```

Generate fresh samples:

```console
python listen.py examples/01_pipeline.hs --audio-dir completed-cues
python listen.py examples/03_division_failure.hs --audio-dir failed-cues
```

A failed task run intentionally returns exit code 1, including after export.
A successful run returns 0; rejected input returns 2. Audio playback is never
started by these export commands.
