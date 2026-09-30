"""Explainable reliability score.

risk(finding) = SEVERITY_WEIGHT[severity] * confidence
risk(mode)    = max over that mode's findings           (repeats of one problem are not double counted)
risk(trace)   = 1 - prod(1 - risk(mode))                (independent failure modes combine like noisy-OR)
score         = round(100 * (1 - risk(trace)))          (100 = clean, 0 = certainly broken)
status        = FAIL if score < 60, WARN if < 85, else PASS
"""
from __future__ import annotations

from typing import Dict, List

from .models import Finding

SEVERITY_WEIGHT = {"low": 0.10, "medium": 0.25, "high": 0.55, "critical": 0.90}


def finding_risk(f: Finding) -> float:
    return SEVERITY_WEIGHT[f.severity] * f.confidence


def score_trace(findings: List[Finding], fail_below: int = 60, warn_below: int = 85) -> Dict:
    per_mode: Dict[str, float] = {}
    for f in findings:
        per_mode[f.mode] = max(per_mode.get(f.mode, 0.0), finding_risk(f))
    keep = 1.0
    for r in per_mode.values():
        keep *= 1 - r
    score = round(100 * keep)
    status = "FAIL" if score < fail_below else "WARN" if score < warn_below else "PASS"
    return {"score": score, "status": status, "mode_risk": {k: round(v, 3) for k, v in per_mode.items()}}
