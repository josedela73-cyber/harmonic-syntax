# Accessibility goals and current limits

This is an early prototype. No blind or low-vision participant study, NVDA,
JAWS, VoiceOver, refreshable-braille, or hearing-access evaluation has been
completed. Automated checks do not stand in for these evaluations.

## Implemented design choices

- Plain text on request, including exact operation names, inputs, and errors.
- Line-based keyboard navigation without timed key presses.
- No automatic sounds, microphone, bundled speech service, or telemetry.
- Explicit play and stop commands; audio export is separate from playback.
- A text-only mode that disables interactive audio.
- Matching text transcripts for exported sound summaries.
- Volume and presentation-duration options that do not change system volume.
- Text navigation remains available when playback cannot start.

These choices are informed by W3C's guidance on
[keyboard access](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)
and [audio control](https://www.w3.org/WAI/WCAG22/Understanding/audio-control.html).
They are not a declaration of conformance for this terminal application.

## Known gaps and questions

- Speech comes from the user's screen reader. Terminal behavior and reading
  order have not been checked with individual assistive technologies.
- The trace reader examines a completed run; it does not provide live progress
  or announce pending dependencies while the engine is running.
- Cues may mask speech or require too much pitch discrimination. Text remains
  available; suggestions for alternative cues and sound-off use are welcome.
- Octave folding can make different task notes sound identical. The current
  sound mapping does not uniquely identify every task or state.
- Playback invocation on Windows and macOS is covered with mocks, not a claim
  of successful listening on those platforms. Missing Linux players are handled
  without disabling text navigation.
- A detected failure has a dedicated sound, but a logically incorrect program
  can finish without failing. Sounds do not certify the correctness of answers.
- There is no tactile interface, braille-specific navigation, graphical editor,
  speech recognition, or mobile user interface in this release.

## Proposed feedback exercise

With willing blind and low-vision programmers, compare the person's usual
workflow with the same workflow plus optional cues. Let participants learn the
controls first, alternate which condition comes first, and use different but
matched tasks to reduce answer memorization. Record error-finding accuracy,
time, false alarms, effort, and preference. Participation and sharing details
should be optional. No such study has been run for this project yet.
