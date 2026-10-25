"""Checks of explicit data flow, stage ordering, and controlled failures."""

from pathlib import Path
import random
import re
import unittest
from unittest.mock import patch

import harmonic as hs
import ordinary_pipeline as ordinary

ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "examples/01_pipeline.hs").read_text(encoding="utf-8")
EXPECTED = {"total": 500500, "n": 1000, "high": 1000, "average": 500.5,
            "normalized_max": 1.0, "reconstructed_total": 500500.0,
            "adjusted_average": 501.5}


class DependencyTests(unittest.TestCase):
    def test_pipeline_produces_all_seven_known_outputs(self):
        result = hs.run(hs.compile_score(SOURCE))
        self.assertEqual(result["outputs"], EXPECTED)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([len(s.calls) for s in hs.compile_score(SOURCE).steps], [3, 2, 2])

    def test_consumer_trace_contains_actual_producer_values(self):
        result = hs.run(hs.compile_score(SOURCE))
        by_name = {r["output"]: r for r in result["operations"]}
        self.assertEqual(by_name["average"]["inputs"], ["total", "n"])
        self.assertEqual(by_name["average"]["input_values"], [500500, 1000])
        self.assertEqual(by_name["adjusted_average"]["input_values"], [500.5, 1.0])

    def test_every_consumer_starts_after_all_its_producers_finish(self):
        result = hs.run(hs.compile_score(SOURCE), delay_ms=10)
        by_name = {r["output"]: r for r in result["operations"]}
        for record in result["operations"]:
            for name in record["inputs"]:
                if name != "data":
                    self.assertLess(by_name[name]["step"], record["step"])
                    self.assertLessEqual(by_name[name]["end_s"], record["start_s"])

    def test_siblings_overlap_within_every_stage(self):
        result = hs.run(hs.compile_score(SOURCE), delay_ms=30)
        for index in range(3):
            records = [r for r in result["operations"] if r["step"] == index]
            self.assertLess(max(r["start_s"] for r in records), min(r["end_s"] for r in records))

    def test_serial_control_preserves_outputs_and_removes_overlap(self):
        result = hs.run(hs.compile_score(SOURCE), delay_ms=5, serial=True)
        self.assertEqual(result["outputs"], EXPECTED)
        records = result["operations"]
        self.assertTrue(all(a["end_s"] <= b["start_s"] for a, b in zip(records, records[1:])))

    def test_dependency_inside_one_chord_is_rejected(self):
        source = (ROOT / "examples/02_wrong_chord.hs").read_text()
        with self.assertRaisesRegex(hs.ScoreError, "same-chord dependency"):
            hs.compile_score(source)

    def test_later_producer_cannot_be_consumed_early(self):
        source = SOURCE.replace("[C4 E4 G4] [A4 B4] [D5 F5]", "[A4 B4] [C4 E4 G4] [D5 F5]")
        with self.assertRaisesRegex(hs.ScoreError, "not yet available"):
            hs.compile_score(source)

    def test_undefined_symbol_is_rejected_even_in_unused_binding(self):
        with self.assertRaisesRegex(hs.ScoreError, "Undefined input"):
            hs.compile_score("C4 = sum(missing) -> result\nz")

    def test_circular_and_self_dependencies_are_rejected(self):
        for source in ("C4 = add(b, b) -> a\nE4 = add(a, a) -> b\nz",
                       "C4 = multiply(a, a) -> a\nz"):
            with self.subTest(source=source), self.assertRaisesRegex(hs.ScoreError, "Circular"):
                hs.compile_score(source)

    def test_argument_text_cannot_be_an_expression_or_external_action(self):
        for argument in ("data[0]", "__import__('os')", "data;open", "data,", "'data'"):
            with self.subTest(argument=argument), self.assertRaises(hs.ScoreError):
                hs.compile_score(f"C4 = sum({argument}) -> result\nC4")

    def test_text_and_series_cannot_be_used_as_scalar_numbers(self):
        for source in ("C4 = checksum(data) -> text\nE4 = add(text, text) -> result\nC4 E4",
                       "C4 = divide(data, data) -> result\nC4",
                       "C4 = sum(data) -> total\nE4 = count(total) -> n\nC4 E4"):
            with self.subTest(source=source), self.assertRaisesRegex(hs.ScoreError, "Type mismatch"):
                hs.compile_score(source)

    def test_wrong_arity_is_rejected(self):
        for source in ("C4 = divide\nC4", "C4 = add(data) -> x\nC4", "C4 = sum() -> x\nC4"):
            with self.subTest(source=source), self.assertRaisesRegex(hs.ScoreError, "expects"):
                hs.compile_score(source)

    def test_reserved_input_and_duplicate_writers_are_rejected(self):
        for source in ("C4 = sum(data) -> data\nC4",
                       "C4 = sum(data) -> total\nE4 = count(data) -> total\n[C4 E4]"):
            with self.subTest(source=source), self.assertRaisesRegex(hs.ScoreError, "multiple writers or is reserved"):
                hs.compile_score(source)

    def test_repeat_cannot_overwrite_named_output(self):
        with self.assertRaisesRegex(hs.ScoreError, "single-assignment"):
            hs.compile_score("C4 = sum(data) -> total\n|: C4 :|2")

    def test_repeated_note_cannot_overwrite_named_output(self):
        with self.assertRaisesRegex(hs.ScoreError, "single-assignment"):
            hs.compile_score("C4 = sum(data) -> total\nC4 C4")

    def test_failed_stage_publishes_none_of_its_outputs_and_stops(self):
        result = hs.run(hs.compile_score((ROOT / "examples/03_division_failure.hs").read_text()))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["completed_events"], 3)
        self.assertEqual(len(result["operations"]), 4)
        self.assertEqual([r["status"] for r in result["operations"][-2:]], ["error", "ok"])
        self.assertNotIn("impossible", result["outputs"])
        self.assertNotIn("peer", result["outputs"])
        self.assertNotIn("later", result["outputs"])

    def test_prior_successful_stages_remain_in_the_failure_report(self):
        result = hs.run(hs.compile_score((ROOT / "examples/03_division_failure.hs").read_text()))
        self.assertEqual(result["outputs"], {"total": 500500, "zero": 0})
        self.assertIn("ZeroDivisionError", result["operations"][-2]["error"])

    def test_integer_growth_limit_blocks_oversized_results(self):
        source = ("tempo 6000\nC4 = sum(data) -> a\nE4 = multiply(a, a) -> b\n"
                  "G4 = multiply(b, b) -> c\nA4 = multiply(c, c) -> d\nB4 = multiply(d, d) -> too_large\n"
                  "C4 E4 G4 A4 B4")
        result = hs.run(hs.compile_score(source), values=(10**9,))
        self.assertEqual(result["status"], "error")
        self.assertIn("256 bits", result["operations"][-1]["error"])
        self.assertNotIn("too_large", result["outputs"])

    def test_non_finite_float_result_cannot_be_published(self):
        notes = ["G4", "A4", "B4", "C5", "D5", "E5", "F5"]
        lines = ["tempo 6000", "C4 = sum(data) -> total", "E4 = count(data) -> n",
                 "G4 = divide(total, n) -> v0"]
        lines.extend(f"{note} = multiply(v{i-1}, v{i-1}) -> v{i}" for i, note in enumerate(notes[1:], 1))
        lines.append("C4 E4 " + " ".join(notes))
        result = hs.run(hs.compile_score("\n".join(lines)), values=(10**9,))
        self.assertEqual(result["status"], "error")
        self.assertIn("not finite", result["operations"][-1]["error"])
        self.assertNotIn("v6", result["outputs"])

    def test_twelve_varied_datasets_match_independent_python(self):
        generator = random.Random(20261025)
        datasets = [(0,), (-4, -2, -7), (1, 2, 3), tuple(range(1, 1001))]
        datasets += [tuple(generator.randint(-1000, 1000) for _ in range(n)) for n in range(1, 9)]
        program = hs.compile_score(SOURCE)
        for values in datasets:
            with self.subTest(values=values[:4]):
                result = hs.run(program, values=values)
                self.assertEqual(result["outputs"], ordinary.expected_outputs(values))
                self.assertEqual(result["outputs"], ordinary.run(values)["outputs"])

    def test_transposition_with_rebound_notes_preserves_dataflow(self):
        mapping = dict(zip(["C4", "E4", "G4", "A4", "B4", "D5", "F5"],
                           ["D4", "F#4", "A4", "B4", "C#5", "E5", "G5"]))
        transposed = re.sub(hs.NOTE, lambda match: mapping[match.group()], SOURCE)
        self.assertEqual(hs.run(hs.compile_score(transposed))["outputs"], EXPECTED)

    def test_consistent_symbol_renaming_preserves_values(self):
        mapping = {"total": "subtotal", "n": "items", "average": "mean"}
        renamed = re.sub(r"\b(?:total|n|average)\b", lambda match: mapping[match.group()], SOURCE)
        outputs = hs.run(hs.compile_score(renamed))["outputs"]
        self.assertEqual(outputs, {mapping.get(name, name): value for name, value in EXPECTED.items()})

    def test_same_musical_structure_with_wrong_arithmetic_gives_wrong_result(self):
        source = (ROOT / "examples/04_semantic_mutation.hs").read_text()
        result = hs.run(hs.compile_score(source))
        self.assertEqual(result["status"], "ok")
        self.assertNotEqual(result["outputs"], EXPECTED)
        self.assertEqual(result["outputs"]["reconstructed_total"], 499500000)

    def test_invalid_late_dependency_cannot_partially_execute(self):
        source = SOURCE.replace("D5 = multiply(average, n)", "D5 = multiply(unknown, n)")
        with patch.object(hs, "compute") as compute, self.assertRaises(hs.ScoreError):
            hs.run(hs.compile_score(source))
        compute.assert_not_called()

    def test_rests_do_not_publish_results_or_break_dependencies(self):
        source = SOURCE.replace("[C4 E4 G4] [A4 B4] [D5 F5]", "[C4 E4 G4] z2 [A4 B4] [D5 F5]")
        result = hs.run(hs.compile_score(source))
        self.assertEqual(result["outputs"], EXPECTED)
        self.assertEqual(result["completed_events"], 4)
        later = [r for r in result["operations"] if r["step"] == 2]
        self.assertTrue(all(r["start_s"] >= result["events"][1]["end_s"] for r in later))

    def test_plan_exposes_inputs_and_outputs_without_running_tasks(self):
        with patch.object(hs, "compute") as compute:
            planned = hs.plan(hs.compile_score(SOURCE))
        compute.assert_not_called()
        call = planned["events"][1]["calls"][0]
        self.assertEqual(call, {"note": "A4", "task": "divide", "inputs": ["total", "n"], "output": "average"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
