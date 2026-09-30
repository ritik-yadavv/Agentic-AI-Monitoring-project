"""Evaluation against self-labelled traces: per-mode P/R/F1 (+Wilson CIs), trace-level metrics,
step localisation accuracy, per-split / per-difficulty slices and an error list."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List

from .models import FAILURE_MODES, Trace
from .monitor import Monitor


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))


def _metrics(rows: List[Dict]) -> Dict:
    out = {}
    for mode in FAILURE_MODES:
        tp = fp = fn = tn = 0
        for r in rows:
            a, p = r["labels"].get(mode, False), mode in r["predicted"]
            tp += a and p; fp += (not a) and p; fn += a and (not p); tn += (not a) and (not p)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
        out[mode] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "support": tp + fn,
                     "precision": prec, "recall": rec, "f1": f1,
                     "precision_ci": wilson(tp, tp + fp), "recall_ci": wilson(tp, tp + fn)}
    tp = sum(m["tp"] for m in out.values()); fp = sum(m["fp"] for m in out.values()); fn = sum(m["fn"] for m in out.values())
    p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
    out["_micro"] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}
    # trace-level "is anything wrong?"
    healthy = [r for r in rows if not any(r["labels"].values())]
    bad = [r for r in rows if any(r["labels"].values())]
    out["_trace_level"] = {
        "n": len(rows), "n_healthy": len(healthy), "n_unhealthy": len(bad),
        "healthy_flagged_any": sum(1 for r in healthy if r["predicted"]),
        "healthy_status_fail_or_warn": sum(1 for r in healthy if r["status"] != "PASS"),
        "unhealthy_status_fail_or_warn": sum(1 for r in bad if r["status"] != "PASS"),
        "unhealthy_status_fail": sum(1 for r in bad if r["status"] == "FAIL"),
        "healthy_status_fail": sum(1 for r in healthy if r["status"] == "FAIL"),
    }
    loc = [(m, r) for r in rows for m in r["predicted"] if r["labels"].get(m) and r["fault_steps"].get(m)]
    hit = sum(1 for m, r in loc if {s for f in r["report"]["findings"] if f["mode"] == m for s in f["step_ids"]} & set(r["fault_steps"][m]))
    out["_localisation"] = {"n": len(loc), "hit": hit, "accuracy": hit / len(loc) if loc else None}
    return out


def evaluate(traces: List[Trace], monitor: Monitor = None) -> Dict:
    monitor = monitor or Monitor()
    rows = []
    for t in traces:
        rep = monitor.run(t)
        rows.append({"trace": t, "report": rep, "trace_id": t.trace_id, "labels": t.labels, "fault_steps": t.fault_steps,
                     "predicted": {f["mode"] for f in rep["findings"]}, "status": rep["status"], "score": rep["score"],
                     "split": t.meta.get("split", "all"), "source": t.meta.get("source", "?"),
                     "difficulty": t.meta.get("difficulty", "normal")})
    slices = defaultdict(list)
    for r in rows:
        slices[f"split={r['split']}"].append(r)
        slices[f"source={r['source']}"].append(r)
        if r["difficulty"] == "hard":
            slices["difficulty=hard"].append(r)
    errors = []
    for r in rows:
        for m in FAILURE_MODES:
            a, p = r["labels"].get(m, False), m in r["predicted"]
            if a != p:
                errors.append({"trace_id": r["trace_id"], "split": r["split"], "mode": m, "type": "false_negative" if a else "false_positive",
                               "note": r["trace"].meta.get("note", ""),
                               "detail": [f["message"] for f in r["report"]["findings"] if f["mode"] == m]})
    return {"n_traces": len(rows), "overall": _metrics(rows),
            "slices": {k: {"n": len(v), **_metrics(v)} for k, v in sorted(slices.items())},
            "errors": errors, "traces": [{**r["report"], "split": r["split"], "source": r["source"], "difficulty": r["difficulty"],
                                          "labels": [m for m, v in r["labels"].items() if v]} for r in rows], "_rows": rows}
