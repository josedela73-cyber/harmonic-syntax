"""Independent ordinary-Python implementation of the seven-task comparison.

No imports from the musical language; no score parser. Each stage is an
explicit group of functions, followed by a join before results are consumed.
"""

from concurrent.futures import ThreadPoolExecutor
import threading
import time


def expected_outputs(data: tuple[int, ...]) -> dict:
    total = sum(data)
    n = len(data)
    high = max(data)
    average = total / n
    normalized_max = high / n
    return {"total": total, "n": n, "high": high, "average": average,
            "normalized_max": normalized_max, "reconstructed_total": average * n,
            "adjusted_average": average + normalized_max}


def run(data: tuple[int, ...], *, delay_ms: int = 0, serial: bool = False) -> dict:
    began = time.perf_counter()
    outputs, records, events = {}, [], []

    def work(name, function, index):
        start = time.perf_counter() - began
        if delay_ms:
            time.sleep(delay_ms / 1000)
        value = function()
        return {"step": index, "output": name, "value": value, "status": "ok",
                "start_s": start, "end_s": time.perf_counter() - began,
                "thread": threading.current_thread().name}

    def stage(jobs, index, pool):
        start = time.perf_counter()
        if serial:
            completed = [work(name, function, index) for name, function in jobs]
        else:
            futures = [pool.submit(work, name, function, index) for name, function in jobs]
            completed = [future.result() for future in futures]
        outputs.update({r["output"]: r["value"] for r in completed})
        records.extend(completed)
        remaining = .01 - (time.perf_counter() - start)
        if remaining > 0:
            time.sleep(remaining)
        events.append({"step": index, "start_s": start - began,
                       "end_s": time.perf_counter() - began, "status": "ok"})

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ordinary") as pool:
        stage([("total", lambda: sum(data)), ("n", lambda: len(data)),
               ("high", lambda: max(data))], 0, pool)
        # Default arguments capture prior-stage values before workers start.
        stage([("average", lambda t=outputs["total"], n=outputs["n"]: t / n),
               ("normalized_max", lambda h=outputs["high"], n=outputs["n"]: h / n)], 1, pool)
        stage([("reconstructed_total", lambda a=outputs["average"], n=outputs["n"]: a * n),
               ("adjusted_average", lambda a=outputs["average"], m=outputs["normalized_max"]: a + m)], 2, pool)
    return {"status": "ok", "elapsed_s": time.perf_counter() - began,
            "outputs": outputs, "operations": records, "events": events}
