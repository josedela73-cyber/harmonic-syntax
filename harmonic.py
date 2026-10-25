#!/usr/bin/env python3
"""Harmonic Syntax: a bounded task notation with explicit result dependencies.

Python 3.10+; standard library only. This is its own notation, NOT an ABC
or MIDI reader. Scores can call only the fixed arithmetic built-ins below.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import threading
import time

VERSION = "0.3.0"
# Each built-in has fixed argument and output types. No user-supplied code.
SPECS = {name: (("numbers",), "number")
         for name in ("sum", "count", "minimum", "maximum", "squares", "fail")}
SPECS["checksum"] = (("numbers",), "text")
SPECS.update({name: (("number", "number"), "number")
              for name in ("add", "subtract", "multiply", "divide")})
TASKS = frozenset(SPECS)
NOTE = r"[A-G](?:#|b)?[0-8]"
SYMBOL = r"[a-z][a-z0-9_]{0,31}"
MAX_SOURCE = 32_768
MAX_EVENTS = 64
MAX_CALLS = 256
MAX_BEATS = 16
MAX_CHORD = 8
MAX_REPEAT = 8
MAX_DEPTH = 4
DEMO_DATA = tuple(range(1, 1001))


class ScoreError(ValueError):
    """The entire score is rejected before any operation is scheduled."""


@dataclass(frozen=True)
class Call:
    note: str
    task: str
    inputs: tuple[str, ...] = ("data",)
    output: str | None = None


@dataclass(frozen=True)
class Step:
    calls: tuple[Call, ...]
    beats: Fraction


@dataclass(frozen=True)
class Program:
    tempo: int
    steps: tuple[Step, ...]


def pitch(note: str) -> int:
    if re.fullmatch(NOTE, note) is None:
        raise ScoreError(f"Invalid note: {note!r}")
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[note[0]]
    accidental = 1 if "#" in note else -1 if "b" in note else 0
    return 12 * (int(note[-1]) + 1) + base + accidental


def _tokens(body: str) -> list[str]:
    pattern = re.compile(r"\s+|\|:|:\||\[|\]|" + NOTE + r"|z|[0-9]{1,6}|/")
    items = []
    position = 0
    while position < len(body):
        match = pattern.match(body, position)
        if not match:
            line = body.count("\n", 0, position) + 1
            raise ScoreError(f"Unexpected character on line {line}: {body[position:position+16]!r}")
        token = match.group()
        if not token.isspace():
            items.append(token)
        position = match.end()
    return items


class _Parser:
    def __init__(self, tokens: list[str], bindings: dict[int, Call]):
        self.tokens = tokens
        self.bindings = bindings
        self.index = 0

    def peek(self) -> str:
        return self.tokens[self.index] if self.index < len(self.tokens) else ""

    def pop(self) -> str:
        token = self.peek()
        if not token:
            raise ScoreError("Unexpected end of score")
        self.index += 1
        return token

    def duration(self) -> Fraction:
        numerator = int(self.pop()) if self.peek().isdigit() else 1
        denominator = 1
        if self.peek() == "/":
            self.pop()
            if not self.peek().isdigit():
                raise ScoreError("A duration slash must be followed by a positive integer")
            denominator = int(self.pop())
        if numerator <= 0 or denominator <= 0 or denominator > 64:
            raise ScoreError("Durations must be positive; denominator is at most 64")
        value = Fraction(numerator, denominator)
        if value > 8:
            raise ScoreError("An event may last at most 8 beats")
        return value

    def call(self, note: str) -> Call:
        key = pitch(note)
        if key not in self.bindings:
            raise ScoreError(f"Unbound note: {note}")
        binding = self.bindings[key]
        return Call(note, binding.task, binding.inputs, binding.output)

    def sequence(self, depth: int = 0) -> list[Step]:
        if depth > MAX_DEPTH:
            raise ScoreError("Repeat nesting limit exceeded")
        steps: list[Step] = []
        while self.peek() and self.peek() != ":|":
            token = self.pop()
            if token == "|:":
                repeated = self.sequence(depth + 1)
                if self.pop() != ":|" or not self.peek().isdigit():
                    raise ScoreError("A repeat must end with :| followed by its count")
                count = int(self.pop())
                if not repeated or not 1 <= count <= MAX_REPEAT:
                    raise ScoreError("A repeat needs events and a count from 1 to 8")
                steps.extend(repeated * count)
            elif token == "[":
                notes: list[str] = []
                while self.peek() and self.peek() != "]":
                    note = self.pop()
                    pitch(note)  # reject nested chords, rests, durations, etc.
                    notes.append(note)
                    if len(notes) > MAX_CHORD:
                        raise ScoreError("A chord may contain at most 8 notes")
                if self.pop() != "]" or len(notes) < 2:
                    raise ScoreError("A chord needs at least two notes")
                if len({pitch(n) for n in notes}) != len(notes):
                    raise ScoreError("A chord cannot contain duplicate pitches")
                steps.append(Step(tuple(self.call(n) for n in notes), self.duration()))
            elif token == "z":
                steps.append(Step((), self.duration()))
            elif re.fullmatch(NOTE, token):
                steps.append(Step((self.call(token),), self.duration()))
            else:
                raise ScoreError(f"Unexpected token: {token!r}")
            _check_size(steps)
        return steps


def _check_size(steps: list[Step] | tuple[Step, ...]) -> None:
    if len(steps) > MAX_EVENTS:
        raise ScoreError("Expanded score exceeds 64 events")
    if sum(len(s.calls) for s in steps) > MAX_CALLS:
        raise ScoreError("Expanded score exceeds 256 operations")
    if sum((s.beats for s in steps), Fraction()) > MAX_BEATS:
        raise ScoreError("Expanded score exceeds 16 beats")


def compile_score(source: str) -> Program:
    """Validate the full input, then return an immutable execution plan."""
    if not isinstance(source, str) or len(source) > MAX_SOURCE:
        raise ScoreError("Score must be text of at most 32768 characters")
    tempo = 120
    saw_tempo = False
    bindings: dict[int, Call] = {}
    body: list[str] = []
    saw_body = False
    for line_number, original in enumerate(source.splitlines(), 1):
        line = original.split("%", 1)[0].strip()
        tempo_match = re.fullmatch(r"tempo\s+([0-9]{1,6})", line)
        binding = re.fullmatch(r"(" + NOTE + r")\s*=\s*([a-z_]+)"
                               r"(?:\(([^()]*)\)\s*->\s*(" + SYMBOL + r"))?", line)
        if not line:
            body.append("")
        elif tempo_match:
            if saw_body or saw_tempo:
                raise ScoreError(f"Line {line_number}: tempo must appear once, before events")
            tempo = int(tempo_match[1])
            if not 60 <= tempo <= 6000:
                raise ScoreError("Tempo must be from 60 to 6000 beats per minute")
            saw_tempo = True
            body.append("")
        elif binding:
            if saw_body:
                raise ScoreError(f"Line {line_number}: bindings must precede events")
            note, task, arguments, output = binding.groups()
            if task not in TASKS:
                raise ScoreError(f"Unknown built-in: {task!r}")
            inputs = (("data",) if arguments is None else
                      tuple(arg.strip() for arg in arguments.split(",")) if arguments.strip() else ())
            if any(re.fullmatch(SYMBOL, name) is None for name in inputs):
                raise ScoreError(f"Line {line_number}: arguments must be symbol names")
            if len(inputs) != len(SPECS[task][0]):
                raise ScoreError(f"Line {line_number}: {task} expects {len(SPECS[task][0])} arguments")
            key = pitch(note)
            if key in bindings:
                raise ScoreError(f"Duplicate pitch binding: {note}")
            bindings[key] = Call(note, task, inputs, output)
            body.append("")
        else:
            saw_body = True
            body.append(line)
    parser = _Parser(_tokens("\n".join(body)), bindings)
    steps = parser.sequence()
    if parser.peek():
        raise ScoreError("Unmatched repeat ending")
    if not steps:
        raise ScoreError("A score must contain at least one event")
    _validate_bindings(bindings)
    program = Program(tempo, tuple(steps))
    _validate_order(program)
    return program


def _validate_bindings(bindings: dict[int, Call]) -> None:
    """Check unique producers, declared symbols, types, and dependency cycles."""
    producers: dict[str, Call] = {}
    types = {"data": "numbers"}
    for call in bindings.values():
        if call.output is None:
            continue
        if call.output in types:
            raise ScoreError(f"Output symbol has multiple writers or is reserved: {call.output}")
        producers[call.output] = call
        types[call.output] = SPECS[call.task][1]
    for call in bindings.values():
        for name, expected in zip(call.inputs, SPECS[call.task][0]):
            if name not in types:
                raise ScoreError(f"Undefined input symbol: {name} (in {call.note})")
            if types[name] != expected:
                raise ScoreError(f"Type mismatch in {call.note}: {name} is {types[name]}, expected {expected}")
    active, visited = set(), set()

    def visit(name: str) -> None:
        if name in active:
            raise ScoreError(f"Circular result dependency involving: {name}")
        if name in visited or name not in producers:
            return
        active.add(name)
        for dependency in producers[name].inputs:
            visit(dependency)
        active.remove(name)
        visited.add(name)

    for name in producers:
        visit(name)


def _validate_order(program: Program) -> None:
    available = {"data"}
    for index, step in enumerate(program.steps):
        pending = {c.output for c in step.calls if c.output is not None}
        for call in step.calls:
            for name in call.inputs:
                if name not in available:
                    detail = "same-chord dependency" if name in pending else "result not yet available"
                    raise ScoreError(f"Step {index}: {call.note} needs {name}: {detail}")
        outputs = [c.output for c in step.calls if c.output is not None]
        if len(outputs) != len(set(outputs)) or any(name in available for name in outputs):
            raise ScoreError(f"Step {index}: named outputs are single-assignment; repeats cannot overwrite them")
        available.update(outputs)


def plan(program: Program) -> dict:
    beat = Fraction()
    events = []
    for index, step in enumerate(program.steps):
        tritones = [[a.note, b.note] for i, a in enumerate(step.calls)
                    for b in step.calls[i + 1:]
                    if (pitch(a.note) - pitch(b.note)) % 12 == 6]
        events.append({"step": index, "logical_beat": str(beat), "beats": str(step.beats),
                       "kind": "rest" if not step.calls else "chord" if len(step.calls) > 1 else "note",
                       "calls": [{"note": c.note, "task": c.task, "inputs": list(c.inputs),
                                  "output": c.output} for c in step.calls],
                       "tritone_pairs_informational_only": tritones})
        beat += step.beats
    return {"version": VERSION, "tempo": program.tempo, "total_beats": str(beat),
            "nominal_duration_s": float(beat * 60 / program.tempo), "events": events}


def compute(task: str, *arguments):
    values = arguments[0]
    if task == "sum":
        return sum(values)
    if task == "count":
        return len(values)
    if task == "minimum":
        return min(values)
    if task == "maximum":
        return max(values)
    if task == "squares":
        return sum(v * v for v in values)
    if task == "checksum":
        return hashlib.sha256(",".join(map(str, values)).encode("ascii")).hexdigest()
    if task == "fail":
        raise RuntimeError("Intentional failure probe")
    if task in {"add", "subtract", "multiply", "divide"}:
        left, right = arguments
        if task == "add":
            return left + right
        if task == "subtract":
            return left - right
        if task == "multiply":
            return left * right
        return left / right
    raise ScoreError(f"Unknown built-in: {task!r}")


def run(program: Program, *, values: tuple[int, ...] = DEMO_DATA,
        delay_ms: int = 0, serial: bool = False) -> dict:
    """Run a compiled plan. Chords join before the next event starts.

    delay_ms is an explicit synthetic I/O-like delay, NOT computation time.
    Duration is a minimum event slot; a slow event makes later events late.
    No CPU-parallelism or hard-real-time guarantee is made.
    """
    if type(delay_ms) is not int or not 0 <= delay_ms <= 200:
        raise ScoreError("Synthetic delay must be an integer from 0 to 200 ms")
    if type(serial) is not bool:
        raise ScoreError("serial must be boolean")
    if not isinstance(values, tuple) or not 1 <= len(values) <= 10_000:
        raise ScoreError("Data must be an immutable tuple of 1 to 10000 integers")
    if any(type(v) is not int or abs(v) > 1_000_000_000 for v in values):
        raise ScoreError("Data values must be integers of magnitude at most 1000000000")
    _validate_order(program)
    started = time.perf_counter()
    records: list[dict] = []
    events: list[dict] = []
    beat = Fraction()
    symbols = {"data": values}

    def work(call: Call, arguments: tuple, index: int, logical_beat: Fraction) -> dict:
        begin = time.perf_counter() - started
        result, error = None, None
        try:
            if delay_ms:
                time.sleep(delay_ms / 1000)
            result = compute(call.task, *arguments)
            # Bound arithmetic growth and reject non-finite results before publication.
            if type(result) is int and result.bit_length() > 256:
                raise ArithmeticError("Integer result exceeds 256 bits")
            if type(result) is float and not math.isfinite(result):
                raise ArithmeticError("Result is not finite")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            result = None
        return {"step": index, "logical_beat": str(logical_beat), "note": call.note,
                "inputs": list(call.inputs), "output": call.output,
                "input_values": [{"kind": "numbers", "count": len(arg)}
                                 if isinstance(arg, tuple) else arg for arg in arguments],
                "task": call.task, "start_s": begin,
                "end_s": time.perf_counter() - started,
                "thread": threading.current_thread().name,
                "status": "error" if error else "ok", "value": result, "error": error}

    status = "ok"
    with ThreadPoolExecutor(max_workers=MAX_CHORD, thread_name_prefix="harmonic") as pool:
        for index, step in enumerate(program.steps):
            begin = time.perf_counter()
            # Resolve only published prior-stage values on the main thread.
            resolved = [tuple(symbols[name] for name in c.inputs) for c in step.calls]
            if serial:
                completed = [work(c, args, index, beat) for c, args in zip(step.calls, resolved)]
            else:
                futures = [pool.submit(work, c, args, index, beat) for c, args in zip(step.calls, resolved)]
                completed = [f.result() for f in futures]  # stable score order; full chord join
            records.extend(completed)
            if any(r["status"] == "error" for r in completed):
                status = "error"
            if status == "ok":
                # Publish this event's outputs together only after every peer succeeds.
                symbols.update({r["output"]: r["value"] for r in completed if r["output"] is not None})
                remaining = float(step.beats * 60 / program.tempo) - (time.perf_counter() - begin)
                if remaining > 0:
                    time.sleep(remaining)
            events.append({"step": index, "logical_beat": str(beat),
                           "start_s": begin - started, "end_s": time.perf_counter() - started,
                           "status": status})
            beat += step.beats
            if status == "error":
                break  # current group finishes; there is no rollback
    return {"version": VERSION, "status": status, "serial_control": serial,
            "synthetic_delay_ms_per_task": delay_ms, "data_count": len(values),
            "elapsed_s": time.perf_counter() - started,
            "outputs": {name: value for name, value in symbols.items() if name != "data"},
            "planned_events": len(program.steps), "completed_events": len(events),
            "operations": records, "events": events}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score", type=Path)
    parser.add_argument("--plan", action="store_true", help="show the compiled plan without running")
    parser.add_argument("--json", action="store_true", help="show complete timings and outputs")
    parser.add_argument("--serial", action="store_true", help="force chords to run sequentially (control)")
    parser.add_argument("--delay-ms", type=int, default=0, help="synthetic wait per task, 0..200")
    args = parser.parse_args(argv)
    try:
        with args.score.open(encoding="utf-8") as handle:
            source = handle.read(MAX_SOURCE + 1)
        program = compile_score(source)
        if args.plan:
            print(json.dumps(plan(program), indent=2))
            return 0
        result = run(program, delay_ms=args.delay_ms, serial=args.serial)
    except (OSError, UnicodeError, ScoreError) as exc:
        print(f"Score rejected: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Harmonic Syntax {VERSION} | {result['status'].upper()}")
        print(f"{result['completed_events']} events; {len(result['operations'])} operations; "
              f"{result['elapsed_s'] * 1000:.1f} ms")
        for record in result["operations"]:
            print(f"  {record['note']}: {record['task']} = "
                  f"{record['error'] or record['value']}")
        if result["outputs"]:
            print("Published outputs:", json.dumps(result["outputs"], sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
