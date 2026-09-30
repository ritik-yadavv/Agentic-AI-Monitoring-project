from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .evaluate import evaluate
from .io import load_traces, parse_react_log
from .monitor import Monitor


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agent_monitor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="run the toy agent with injected faults and write labelled traces")
    g.add_argument("--out", default="data"); g.add_argument("--seed", type=int, default=7); g.add_argument("--split", default="dev"); g.add_argument("--subdir", default="")
    r = sub.add_parser("run", help="monitor one trace file / directory / ReAct .txt log and print reports")
    r.add_argument("path")
    e = sub.add_parser("evaluate", help="evaluate labelled traces; writes dashboard + metrics")
    e.add_argument("data", nargs="?", default="data"); e.add_argument("--out", default="reports")
    d = sub.add_parser("demo", help="run the toy agent live on a goal, optionally with a fault, and monitor it")
    d.add_argument("goal", nargs="?", default="What is the capital of Canada?")
    d.add_argument("--fault", default="none", choices=["none", "loop", "misuse", "hallucination", "drift", "unsafe"])
    a = ap.parse_args(argv)

    if a.cmd == "generate":
        from .sim.generate import generate
        ts = generate(Path(a.out), a.seed, a.split, a.subdir)
        print(f"wrote {len(ts)} traces to {Path(a.out) / a.split / a.subdir}")
    elif a.cmd == "run":
        p = Path(a.path)
        traces = [parse_react_log(p.read_text(), p.stem)] if p.suffix == ".txt" else load_traces(p)
        m = Monitor()
        for t in traces:
            rep = m.run(t)
            print(f"{rep['trace_id']}: {rep['status']} score={rep['score']}")
            for f in rep["findings"]:
                print(f"   [{f['severity']:>8} {f['confidence']:.2f}] {f['mode']} steps={f['step_ids']}: {f['message']}")
    elif a.cmd == "evaluate":
        res = evaluate(load_traces(a.data))
        out = Path(a.out); (out / "traces").mkdir(parents=True, exist_ok=True)
        from .report import dashboard_html, markdown_summary
        (out / "dashboard.html").write_text(dashboard_html(res), encoding="utf-8")
        (out / "summary.md").write_text(markdown_summary(res), encoding="utf-8")
        public = {k: v for k, v in res.items() if k != "_rows"}
        (out / "evaluation.json").write_text(json.dumps(public, indent=2, default=str), encoding="utf-8")
        for t in res["traces"]:
            (out / "traces" / f"{t['trace_id']}.json").write_text(json.dumps(t, indent=2), encoding="utf-8")
        print((out / "summary.md").read_text())
        print(f"Dashboard: {out / 'dashboard.html'}")
    elif a.cmd == "demo":
        from .sim.agent import make_task, run_agent
        from .sim.environment import ToolEnvironment
        from .sim.faults import DriftFault, HallucinationFault, LoopFault, MisuseFault, UnsafeFault
        rng = random.Random(1)
        task = make_task("capital", rng)
        task.goal = a.goal; task.p["country"] = a.goal.rstrip("?").split()[-1]
        pol = {"none": task, "loop": LoopFault(task, rng, "exact", 4), "misuse": MisuseFault(task, rng, "missing"),
               "hallucination": HallucinationFault(task, rng, "entity"), "drift": DriftFault(task, rng), "unsafe": UnsafeFault(task, rng, "sensitive")}[a.fault]
        tr, _ = run_agent(a.goal, pol, ToolEnvironment(), "demo")
        for s in tr.steps:
            print(f"{s.id}. " + (f"{s.tool}({s.arguments}) -> {s.observation}" if s.is_action else f"ANSWER: {s.answer}"))
        rep = Monitor().run(tr)
        print(f"\n{rep['status']} score={rep['score']}")
        for f in rep["findings"]:
            print(f"  {f['mode']} steps={f['step_ids']}: {f['message']}")
    return 0
