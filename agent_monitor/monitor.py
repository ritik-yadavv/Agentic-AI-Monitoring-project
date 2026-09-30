from __future__ import annotations

from typing import Dict, Optional

from .config import MonitorConfig
from .detectors import default_detectors
from .models import Trace
from .scoring import SEVERITY_WEIGHT, score_trace


class Monitor:
    def __init__(self, config: Optional[MonitorConfig] = None, detectors=None):
        self.cfg = config or MonitorConfig()
        self.detectors = detectors or default_detectors(self.cfg)

    def run(self, trace: Trace) -> Dict:
        merged = {}
        for d in self.detectors:
            for f in d.detect(trace):
                if f.confidence < self.cfg.min_confidence:
                    continue
                key = (f.mode, tuple(f.step_ids))
                old = merged.get(key)
                if old is None or (SEVERITY_WEIGHT[f.severity], f.confidence) > (SEVERITY_WEIGHT[old.severity], old.confidence):
                    merged[key] = f
        findings = sorted(merged.values(), key=lambda f: (f.step_ids[0], f.mode))
        sc = score_trace(findings, self.cfg.status_fail_below, self.cfg.status_warn_below)
        return {"trace_id": trace.trace_id, "goal": trace.goal, **sc,
                "findings": [f.as_dict() for f in findings]}
