"""Generate labelled traces by RUNNING the toy agent with injected faults. Labels come from the injection."""
from __future__ import annotations

import random
from pathlib import Path
from typing import List

from ..io import save_trace
from ..models import FAILURE_MODES, Trace
from .agent import TASK_KINDS, make_task, run_agent
from .environment import ToolEnvironment
from .faults import DriftFault, HallucinationFault, LoopFault, MisuseFault, UnsafeFault


def _build(rng, spec: str):
    """spec: healthy | healthy_retry | healthy_giveup | <mode>[:variant] | combo:<a>+<b>"""
    kind = rng.choice(TASK_KINDS)
    fail = {}
    kinds_by_tool = {"weather": "weather", "compare": "weather", "math": "calculator", "capital": "search",
                     "ratio": "search", "file": "read_file"}
    if spec.startswith(("unsafe:inject", "unsafe:hijack")) or spec == "combo:unsafe+hallucination":
        kind = rng.choice(["capital", "ratio"])
    if spec == "hallucination:entity":
        kind = "capital"
    if spec in ("hallucination:number", "combo:looping+hallucination", "combo:tool_misuse+hallucination"):
        kind = rng.choice(["weather", "compare", "math", "ratio", "file"])
    if spec == "combo:unsafe+hallucination":
        kind = "ratio"
    if spec == "hallucination:no_tool":
        kind = rng.choice(["weather", "capital", "compare"])
    task = make_task(kind, rng)
    pol, poison = task, False
    mode, _, var = spec.partition(":")
    if spec == "healthy_retry":
        fail = {kinds_by_tool[kind]: 1}
    elif spec == "healthy_giveup":
        fail = {kinds_by_tool[kind]: 9}
    elif mode == "looping":
        pol = LoopFault(task, rng, var or "exact", n=(6 if var == "cycle" else rng.choice([3, 4, 5])), runaway=(var == "runaway"))
        if var == "runaway":
            pol.variant = "exact"
    elif mode == "tool_misuse":
        pol = MisuseFault(task, rng, var or "missing")
    elif mode == "hallucination":
        if var == "after_error":
            fail = {kinds_by_tool[kind]: 9}
            pol = HallucinationFault(task, rng, "number")
            pol._force = True
        else:
            pol = HallucinationFault(task, rng, var or "number")
    elif mode == "goal_drift":
        pol = DriftFault(task, rng, after=1, n=rng.choice([2, 3]), off_answer=(var != "recover"))
    elif mode == "unsafe":
        poison = var in ("inject", "hijack")
        pol = UnsafeFault(task, rng, var or "shell")
    elif mode == "combo":
        a, b = var.split("+")
        if b == "hallucination":
            pol = HallucinationFault(task, rng, "number")
            pol.inner = {"looping": LoopFault(task, rng, "exact", n=3), "tool_misuse": MisuseFault(task, rng, "unknown"),
                         "unsafe": UnsafeFault(task, rng, "hijack")}[a]
            poison = a == "unsafe"
    return task, pol, ToolEnvironment(fail=fail, poison_next_search=poison)


def _labels(fault_steps):
    return {m: bool(fault_steps.get(m)) for m in FAILURE_MODES}


def generate(out_dir: Path, seed: int, split: str, subdir: str = "", n_healthy=24, per_mode=8, n_hijack=5, n_combo=6) -> List[Trace]:
    rng = random.Random(seed)
    specs = ["healthy"] * (n_healthy - 8) + ["healthy_retry"] * 5 + ["healthy_giveup"] * 3
    plan = {"looping": ["exact", "paraphrase", "cycle", "runaway"], "tool_misuse": ["missing", "type", "unknown", "nonsense"],
            "hallucination": ["number", "entity", "no_tool", "after_error"], "goal_drift": ["", "recover"],
            "unsafe": ["shell", "sensitive", "traversal", "secret", "inject"]}
    for mode, variants in plan.items():
        specs += [f"{mode}:{variants[i % len(variants)]}" for i in range(per_mode)]
    specs += ["unsafe:hijack"] * n_hijack
    specs += [f"combo:{c}+hallucination" for c in ["looping", "tool_misuse", "unsafe"] * (n_combo // 3)]
    traces = []
    for i, spec in enumerate(specs):
        task, pol, env = _build(rng, spec)
        tr, faults = run_agent(task.goal, pol, env, f"{split}{subdir}_{i:03d}_{spec.replace(':', '-').replace('+', '_')}")
        if spec == "hallucination:after_error":       # agent hides a tool outage by inventing a result
            fin = tr.final_step
            fin.answer = f"The result is {rng.randint(21, 39)} based on the latest data."
            faults = {"hallucination": [fin.id]}
        tr.fault_steps, tr.labels = faults, _labels(faults)
        tr.meta = {"split": split, "source": "generated", "spec": spec, "seed": seed}
        traces.append(tr)
    rng.shuffle(traces)
    for t in traces:
        save_trace(t, Path(out_dir) / split / subdir / f"{t.trace_id}.json")
    return traces
