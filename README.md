# Harmonic Syntax

An experimental task language and a plain-text trace explorer with optional
audio cues. We are seeking feedback from blind and low-vision programmers,
screen-reader users, accessibility practitioners, and other interested people.

Version 0.3.0 — early accessibility prototype. **No participant usability study
or screen-reader compatibility evaluation has been completed.** This project
does not establish improved coding accuracy or greater AI intelligence.

## Try it without installing packages

Python 3.10 or later, standard library only. Download and extract the source,
then open a terminal in this folder. On Windows, `py` may replace `python`;
Mac/Linux may need `python3`.

Start with the complete text trace:

```console
python listen.py examples/01_pipeline.hs --transcript
```

Explore one stage at a time, with sound disabled:

```console
python listen.py examples/01_pipeline.hs --text-only
```

Try the same explorer with optional sound commands:

```console
python listen.py examples/01_pipeline.hs
```

Nothing plays automatically. Read each command with Enter; there are no timed
keystrokes or single-key global shortcuts. Commands are:

- `next` or `n`: next completed stage.
- `previous` or `b`: previous stage.
- `first`, `last`: move to an end of the trace.
- `show` or `s`, or an empty command: repeat the current stage's text.
- `play` or `p`: play the current stage's optional cue.
- `stop`: stop this explorer's playback.
- `help` or `h`: list commands.
- `quit` or `q`: leave and stop playback.

Text descriptions list operation names, input values, computed results,
publication status, and errors. Speech is supplied by your own screen reader;
this prototype does not bundle text-to-speech. The terminal output uses plain
lines without color codes or a screen-redrawing interface. How well this works
with particular screen readers still needs evaluation.

## Audio options

Windows playback uses `winsound`; macOS uses `afplay`; Linux uses `paplay` or
`aplay` when available. If there is no supported player, text navigation remains
available. These platform playback paths have automated mock checks; they have
not all been tried on physical devices.

Export portable audio files and matching text instead of playing:

```console
python listen.py examples/01_pipeline.hs --audio-dir exported-cues
python listen.py examples/03_division_failure.hs --audio-dir failure-cues
```

Export produces individual stage WAVs, `overview.wav`, and `transcript.txt`.
The included `samples` folder contains generated examples, with no autoplay.
`--volume 0.1` changes cue amplitude without changing system volume.
`--seconds 0.7` makes each stage's summary sound longer.

The audio is a **summary of a completed run**, not live scheduling or measured
CPU timing. A group of tones represents a group of independent tasks. Notes
are folded by octaves into 220..880 Hz; octave identity is not preserved.
Different notes can therefore sound alike. Exact text is always available.
A two-tone alert follows a stage with an actual task failure. Dissonance never
determines whether a program is valid. Completion sounds or statuses do not
verify that the programmer chose the correct calculation.

Musical training is not a prerequisite for text navigation. Whether the tone
mapping is easy to learn or useful to anyone is an open research question.
We welcome alternative mappings, nonmusical cues, and quieter interaction ideas.

## What the language does

```text
tempo 6000
C4 = sum(data) -> total
E4 = count(data) -> n
A4 = divide(total, n) -> average

[C4 E4] A4
```

`data` is a synthetic immutable tuple of integers 1..1000. The chord computes
two independent results; the next event consumes them and computes 500.5.
The full score is checked before execution. Tasks in the same chord may not
read each other's outputs; named results have one producer. Outputs from a
failed stage are not published, and later stages do not run.

The fixed built-ins are sum, count, minimum, maximum, squares, checksum, add,
subtract, multiply, divide, and an intentional fail probe. There are no shell,
network, arbitrary-code, file-writing, or import instructions in the language.
This application restriction is not an OS sandbox. The CLI reads a selected
score, and audio export writes only to the selected destination.

This is its own notation, not an ABC/MIDI implementation. Variables with
reassignment, general conditional branches, and arbitrary functions are absent.
The engine bounds source size, expanded events, task count, duration, input
values, and result size. Thread concurrency does not establish CPU parallelism.

## Feedback we need

The most useful questions concern real use:

1. Can you discover the commands and move between stages using your usual tools?
2. Are task names, inputs, and failure details easy to locate?
3. Do sound cues help, distract, or interfere with your screen reader?
4. Which controls, text changes, or audio mappings would you prefer?

Use the accessibility feedback or bug-report issue templates, or contribute a
small reproducible example. Tool names and versions are optional. No medical
history or proof of disability is requested. Please use synthetic examples
when sharing traces, because repository issues are public.

See [ACCESSIBILITY.md](ACCESSIBILITY.md), [CONTRIBUTING.md](CONTRIBUTING.md),
and [VALIDATION.md](VALIDATION.md). We aim to design this with people who would
use it, and have not claimed WCAG conformance or user-tested accessibility.

## Run checks

```console
python -m unittest -v
```

The suite covers dependency rules, failure handling, literal task execution,
text navigation, no automatic playback, WAV structure, and player integration
through mocks. These checks cannot establish accessibility or actual audio
quality on a person's hardware.

## Related work

Audio-assisted programming has substantial prior work. In particular,
[CodeTalk](https://www.microsoft.com/en-us/research/project/codetalk/) explored
speech and non-speech cues alongside screen readers. This project is an
independent experiment and does not claim to invent accessible programming.

## License

MIT; see [LICENSE](LICENSE). Created by Jose De La Cruz with AI-assisted
development. Contributions and critical feedback are welcome.
