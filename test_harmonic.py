"""Behavioral checks for the language contract and actual execution."""

from fractions import Fraction
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import harmonic as hs


HEADER = "tempo 6000\nC4 = sum\nE4 = count\nG4 = maximum\nF#4 = minimum\n"


class LanguageTests(unittest.TestCase):
    def test_single_notes_finish_in_score_order(self):
        result = hs.run(hs.compile_score(HEADER + "C4 E4 G4"), delay_ms=10)
        records = result["operations"]
        self.assertEqual([r["value"] for r in records], [500500, 1000, 1000])
        self.assertTrue(all(a["end_s"] <= b["start_s"] for a, b in zip(records, records[1:])))

    def test_chord_has_actual_overlapping_worker_intervals(self):
        result = hs.run(hs.compile_score(HEADER + "[C4 E4 G4]"), delay_ms=40)
        records = result["operations"]
        self.assertLess(max(r["start_s"] for r in records), min(r["end_s"] for r in records))
        self.assertEqual(len({r["thread"] for r in records}), 3)
        self.assertEqual({r["logical_beat"] for r in records}, {"0"})

    def test_serial_control_removes_overlap_for_the_same_chord(self):
        result = hs.run(hs.compile_score(HEADER + "[C4 E4 G4]"), serial=True, delay_ms=10)
        records = result["operations"]
        self.assertTrue(all(a["end_s"] <= b["start_s"] for a, b in zip(records, records[1:])))

    def test_later_event_waits_for_every_chord_peer(self):
        result = hs.run(hs.compile_score(HEADER + "[C4 E4 G4] C4"), delay_ms=20)
        self.assertGreaterEqual(result["operations"][-1]["start_s"],
                                max(r["end_s"] for r in result["operations"][:3]))

    def test_rest_waits_without_executing_any_task(self):
        result = hs.run(hs.compile_score("tempo 6000\nz2"))
        self.assertEqual(result["operations"], [])
        self.assertGreaterEqual(result["events"][0]["end_s"] - result["events"][0]["start_s"], .019)

    def test_rest_delays_following_operation(self):
        result = hs.run(hs.compile_score(HEADER + "z2 C4"))
        self.assertGreaterEqual(result["operations"][0]["start_s"], .019)

    def test_fractional_beats_have_exact_logical_onsets(self):
        program = hs.compile_score(HEADER + "z/4 |: [C4 E4]/2 G4/2 :|2")
        compiled = hs.plan(program)
        self.assertEqual([e["logical_beat"] for e in compiled["events"]],
                         ["0", "1/4", "3/4", "5/4", "7/4"])
        self.assertEqual(compiled["total_beats"], "9/4")

    def test_repeat_performs_each_operation_each_time(self):
        result = hs.run(hs.compile_score(HEADER + "|: C4 E4 :|3"))
        self.assertEqual([r["task"] for r in result["operations"]], ["sum", "count"] * 3)

    def test_nested_repeat_has_expected_order(self):
        program = hs.compile_score(HEADER + "|: C4/4 |: E4/4 G4/4 :|2 :|2")
        self.assertEqual([c.task for s in program.steps for c in s.calls],
                         ["sum", "count", "maximum", "count", "maximum"] * 2)

    def test_transposition_preserves_outputs_with_reassigned_bindings(self):
        first = hs.run(hs.compile_score(HEADER + "[C4 E4 G4]"))
        second = hs.run(hs.compile_score("tempo 6000\nD4 = sum\nF#4 = count\nA4 = maximum\n[D4 F#4 A4]"))
        self.assertEqual([r["value"] for r in first["operations"]],
                         [r["value"] for r in second["operations"]])

    def test_chord_note_order_does_not_change_task_values(self):
        first = hs.run(hs.compile_score(HEADER + "[C4 E4 G4]"))
        second = hs.run(hs.compile_score(HEADER + "[G4 C4 E4]"))
        self.assertEqual({r["task"]: r["value"] for r in first["operations"]},
                         {r["task"]: r["value"] for r in second["operations"]})

    def test_dissonant_chord_executes_and_reports_information_only(self):
        program = hs.compile_score(HEADER + "[C4 F#4]")
        self.assertEqual(hs.plan(program)["events"][0]["tritone_pairs_informational_only"], [["C4", "F#4"]])
        result = hs.run(program)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([r["value"] for r in result["operations"]], [500500, 1])

    def test_consonant_chord_can_fail_and_later_event_is_not_started(self):
        program = hs.compile_score("tempo 6000\nC4 = sum\nE4 = fail\nG4 = maximum\n[C4 E4 G4] C4")
        self.assertEqual(hs.plan(program)["events"][0]["tritone_pairs_informational_only"], [])
        result = hs.run(program)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["completed_events"], 1)
        self.assertEqual(len(result["operations"]), 3)
        self.assertEqual([r["status"] for r in result["operations"]], ["ok", "error", "ok"])

    def test_enharmonic_note_uses_the_same_pitch_binding(self):
        program = hs.compile_score("tempo 6000\nC#4 = sum\nDb4")
        self.assertEqual(hs.run(program)["operations"][0]["value"], 500500)

    def test_sharps_are_not_mistaken_for_comments(self):
        program = hs.compile_score("tempo 6000 % comment\nF#4 = count % comment\nF#4 % comment")
        self.assertEqual(program.steps[0].calls[0].task, "count")

    def test_invalid_late_input_cannot_partially_execute(self):
        with patch.object(hs, "compute") as compute:
            for tail in ("G4", "[C4", "__import__('os')", "|: C4 :|99"):
                with self.subTest(tail=tail), self.assertRaises(hs.ScoreError):
                    hs.run(hs.compile_score("tempo 6000\nC4 = sum\nC4 " + tail))
            compute.assert_not_called()

    def test_unknown_builtins_and_unsafe_text_are_rejected(self):
        for source in ("C4 = shell\nC4", "C4 = eval\nC4", "open('/tmp/x')", "import os"):
            with self.subTest(source=source), self.assertRaises(hs.ScoreError):
                hs.compile_score(source)

    def test_invalid_grammar_is_rejected(self):
        for body in ("", "[C4]", "[C4 E4", "C4]", ":|2", "|: C4", "|: :|2",
                     "[C4 z]", "[[C4 E4] G4]", "C4/", "C4//2", "C4 - E4", "C4???"):
            with self.subTest(body=body), self.assertRaises(hs.ScoreError):
                hs.compile_score(HEADER + body)

    def test_invalid_durations_and_tempos_are_rejected(self):
        for body in ("C40", "C4/0", "C4/65", "C49", "z0", "C40/2"):
            with self.subTest(body=body), self.assertRaises(hs.ScoreError):
                hs.compile_score(HEADER + body)
        for tempo in (0, 59, 6001, 999999):
            with self.subTest(tempo=tempo), self.assertRaises(hs.ScoreError):
                hs.compile_score(f"tempo {tempo}\nz")

    def test_duplicate_pitch_bindings_and_duplicate_chord_pitches_are_rejected(self):
        for source in ("C4 = sum\nC4 = count\nC4", "C4 = sum\nB#3 = count\nC4",
                       HEADER + "[C4 C4]", HEADER + "[C4 B#3]"):
            with self.subTest(source=source), self.assertRaises(hs.ScoreError):
                hs.compile_score(source)

    def test_headers_after_events_or_duplicate_tempo_are_rejected(self):
        for source in (HEADER + "C4\ntempo 600", HEADER + "C4\nA4 = sum", "tempo 600\ntempo 600\nz"):
            with self.subTest(source=source), self.assertRaises(hs.ScoreError):
                hs.compile_score(source)

    def test_expansion_depth_call_and_time_limits(self):
        cases = [HEADER + "z8 z8 z", HEADER + "|: C4/64 :|9",
                 HEADER + "|: |: |: C4/64 :|8 :|8 :|2",
                 HEADER + "|: |: |: |: |: C4/64 :|1 :|1 :|1 :|1 :|1",
                 "%" * (hs.MAX_SOURCE + 1)]
        notes = "C4 D4 E4 F4 G4 A4 B4 C5".split()
        definitions = "\n".join(n + " = sum" for n in notes) + "\n"
        cases.append(definitions + ("[" + " ".join(notes) + "]/64 ") * 33)
        for source in cases:
            with self.subTest(length=len(source)), self.assertRaises(hs.ScoreError):
                hs.compile_score(source)

    def test_chord_width_limit(self):
        notes = "C4 D4 E4 F4 G4 A4 B4 C5 D5".split()
        source = "\n".join(n + " = sum" for n in notes) + "\n[" + " ".join(notes) + "]"
        with self.assertRaises(hs.ScoreError):
            hs.compile_score(source)

    def test_runtime_inputs_are_validated_before_execution(self):
        program = hs.compile_score(HEADER + "C4")
        with patch.object(hs, "compute") as compute:
            for kwargs in ({"values": ()}, {"values": [1, 2]}, {"values": (True,)},
                           {"values": (1.2,)}, {"values": (10**20,)},
                           {"values": tuple(range(10001))}, {"delay_ms": -1},
                           {"delay_ms": 201}, {"delay_ms": 0.5}, {"serial": "yes"}):
                with self.subTest(kwargs=str(kwargs)[:100]), self.assertRaises(hs.ScoreError):
                    hs.run(program, **kwargs)
            compute.assert_not_called()

    def test_all_arithmetic_builtins_on_known_data(self):
        values = (-3, 2, 5)
        expected = {"sum": 4, "count": 3, "minimum": -3, "maximum": 5, "squares": 38}
        # A separate standard-library oracle for the literal encoded fixture.
        import hashlib
        expected["checksum"] = hashlib.sha256(b"-3,2,5").hexdigest()
        for task, value in expected.items():
            with self.subTest(task=task):
                program = hs.compile_score(f"tempo 6000\nC4 = {task}\nC4")
                self.assertEqual(hs.run(program, values=values)["operations"][0]["value"], value)

    def test_slow_operations_shift_later_events_instead_of_overlapping_them(self):
        result = hs.run(hs.compile_score(HEADER + "C4/2 E4/2"), delay_ms=30)
        self.assertEqual([r["logical_beat"] for r in result["operations"]], ["0", "1/2"])
        self.assertGreater(result["operations"][1]["start_s"], .025)
        self.assertGreaterEqual(result["operations"][1]["start_s"], result["operations"][0]["end_s"])

    def test_cli_plan_success_error_and_rejection_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "score.hs"
            with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO):
                path.write_text(HEADER + "[C4 E4 G4]", encoding="utf-8")
                self.assertEqual(hs.main([str(path), "--plan"]), 0)
                self.assertEqual(hs.main([str(path), "--json"]), 0)
                path.write_text("tempo 6000\nC4 = fail\nC4", encoding="utf-8")
                self.assertEqual(hs.main([str(path)]), 1)
                path.write_text(HEADER + "BAD", encoding="utf-8")
                self.assertEqual(hs.main([str(path)]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
