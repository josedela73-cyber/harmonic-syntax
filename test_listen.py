import contextlib
import io
import math
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import wave

import harmonic as hs
import listen

ROOT = Path(__file__).resolve().parent


def execute(name="01_pipeline.hs"):
    return hs.run(hs.compile_score((ROOT / "examples" / name).read_text()))


class ExplorerTests(unittest.TestCase):
    def test_transcript_contains_actual_inputs_and_published_results(self):
        text = listen.transcript(execute())
        self.assertIn("total equals 500500; n equals 1000", text)
        self.assertIn("Computed result: 500.5. Published as average.", text)
        self.assertIn("3 of 3 stages ran", text)

    def test_failed_stage_distinguishes_computation_from_publication(self):
        execution = execute("03_division_failure.hs")
        text = listen.transcript(execution)
        self.assertIn("ZeroDivisionError", text)
        self.assertIn("Not published because a task in this stage failed", text)
        self.assertIn("Later stages did not run", text)
        self.assertEqual(len(listen.stages(execution)), 3)

    def test_sound_generation_is_deterministic_and_bounded(self):
        frame = listen.stages(execute())[0]
        first = listen.stage_samples(frame)
        self.assertEqual(first, listen.stage_samples(frame))
        self.assertEqual(len(first), round(.35 * listen.SAMPLE_RATE))
        self.assertTrue(any(first))
        self.assertLessEqual(max(abs(value) for value in first), math.ceil(32767 * .15))

    def test_zero_volume_has_no_nonzero_samples(self):
        frame = listen.stages(execute())[0]
        self.assertFalse(any(listen.stage_samples(frame, volume=0)))

    def test_rest_renders_silence(self):
        frame = listen.stages(hs.run(hs.compile_score("tempo 6000\nz")))[0]
        self.assertFalse(any(listen.stage_samples(frame)))
        self.assertIn("Rest", frame["text"])

    def test_error_alert_comes_from_run_status_not_dissonance(self):
        dissonant = hs.run(hs.compile_score("tempo 6000\nC4 = sum\nF#4 = count\n[C4 F#4]"))
        normal_length = len(listen.stage_samples(listen.stages(dissonant)[0]))
        failed_frame = listen.stages(execute("03_division_failure.hs"))[-1]
        self.assertEqual(normal_length, round(.35 * listen.SAMPLE_RATE))
        self.assertGreater(len(listen.stage_samples(failed_frame)), normal_length)

    def test_all_supported_note_pitches_fold_into_the_tone_palette(self):
        for octave in range(9):
            for letter in "CDEFGAB":
                frequency = listen._frequency(letter + str(octave))
                self.assertGreaterEqual(frequency, 220 - 1e-8)
                self.assertLessEqual(frequency, 880 + 1e-8)

    def test_invalid_volume_and_duration_are_rejected(self):
        frame = listen.stages(execute())[0]
        for kwargs in ({"volume": -1}, {"volume": 1.1}, {"volume": float("nan")},
                       {"seconds": 0}, {"seconds": 2.1}, {"seconds": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                listen.stage_samples(frame, **kwargs)

    def test_wav_export_matches_pcm_contract_and_has_transcript(self):
        execution = execute()
        with tempfile.TemporaryDirectory() as directory:
            paths = listen.export(execution, Path(directory))
            self.assertEqual(len(paths), 5)
            self.assertEqual((Path(directory) / "transcript.txt").read_text(), listen.transcript(execution))
            with wave.open(str(Path(directory) / "stage-01.wav"), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.getframerate(), listen.SAMPLE_RATE)
                self.assertEqual(audio.getnframes(), round(.35 * listen.SAMPLE_RATE))

    def test_navigation_never_plays_automatically(self):
        commands = iter(["n", "b", "first", "last", "show", "", "help", "unknown", "q"])
        output = []
        with patch.object(listen, "Player") as player:
            listen.explore(execute(), read=lambda _: next(commands), say=output.append)
        player.return_value.play.assert_not_called()
        self.assertTrue(any("Stage 1." in item for item in output))
        self.assertTrue(any("Stage 3." in item for item in output))
        self.assertTrue(any("Unknown command" in item for item in output))

    def test_text_only_mode_disables_explicit_play(self):
        commands = iter(["play", "q"])
        output = []
        with patch.object(listen, "Player") as player:
            listen.explore(execute(), text_only=True, read=lambda _: next(commands), say=output.append)
        player.return_value.play.assert_not_called()
        self.assertTrue(any("Sound is disabled" in item for item in output))

    def test_explicit_play_invokes_player_and_quit_stops_it(self):
        commands = iter(["p", "stop", "q"])
        with patch.object(listen, "Player") as player:
            listen.explore(execute(), read=lambda _: next(commands), say=lambda _: None)
        player.return_value.play.assert_called_once()
        self.assertGreaterEqual(player.return_value.stop.call_count, 2)

    def test_failed_audio_does_not_break_text_navigation(self):
        commands = iter(["p", "n", "q"])
        output = []
        with patch.object(listen, "Player") as player:
            player.return_value.play.side_effect = OSError("test audio unavailable")
            listen.explore(execute(), read=lambda _: next(commands), say=output.append)
        self.assertTrue(any("Audio unavailable" in item for item in output))
        self.assertTrue(any("Stage 2." in item for item in output))

    def test_end_of_input_cleans_up_playback(self):
        with patch.object(listen, "Player") as player:
            listen.explore(execute(), read=MagicMock(side_effect=EOFError), say=lambda _: None)
        player.return_value.stop.assert_called()

    def test_missing_linux_player_is_reported_without_launch(self):
        player = listen.Player()
        with patch.object(listen.sys, "platform", "linux"), patch.object(listen.shutil, "which", return_value=None), patch.object(listen.subprocess, "Popen") as launch:
            message = player.play(Path("cue.wav"))
        launch.assert_not_called()
        self.assertIn("Text navigation still works", message)

    def test_player_uses_an_argument_list_and_stops_its_own_process(self):
        player = listen.Player()
        with patch.object(listen.sys, "platform", "darwin"), patch.object(listen.shutil, "which", return_value="/usr/bin/afplay"), patch.object(listen.subprocess, "Popen") as launch:
            launch.return_value.poll.return_value = None
            player.play(Path("a cue.wav"))
            player.stop()
        self.assertEqual(launch.call_args.args[0], ["/usr/bin/afplay", "a cue.wav"])
        self.assertNotIn("shell", launch.call_args.kwargs)
        launch.return_value.terminate.assert_called_once()

    def test_windows_playback_is_async_and_stoppable(self):
        module = types.SimpleNamespace(PlaySound=MagicMock(), SND_FILENAME=1, SND_ASYNC=2)
        player = listen.Player()
        with patch.object(listen.sys, "platform", "win32"), patch.dict("sys.modules", {"winsound": module}):
            player.play(Path("cue.wav"))
            player.stop()
        self.assertEqual(module.PlaySound.call_args_list[0].args, ("cue.wav", 3))
        self.assertEqual(module.PlaySound.call_args_list[-1].args, (None, 0))

    def test_cli_transcript_does_not_initialize_playback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(listen, "Player") as player:
            code = listen.main([str(ROOT / "examples/01_pipeline.hs"), "--transcript"])
        player.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("average: 500.5", output.getvalue())

    def test_cli_failure_export_retains_failure_exit_code(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            code = listen.main([str(ROOT / "examples/03_division_failure.hs"), "--audio-dir", directory])
            self.assertEqual(code, 1)
            self.assertTrue((Path(directory) / "overview.wav").is_file())
            self.assertIn("Later stages did not run", (Path(directory) / "transcript.txt").read_text())

    def test_cli_invalid_options_fail_before_running(self):
        for flags in (["--volume", "nan"], ["--seconds", "0"], ["--text-only", "--audio-dir", "unused"]):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()), patch.object(hs, "run") as runner:
                self.assertEqual(listen.main([str(ROOT / "examples/01_pipeline.hs")] + flags), 2)
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
