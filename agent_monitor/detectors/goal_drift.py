"""Goal drift: sustained actions unrelated to the stated goal.

An action step is *relevant* if its arguments share a content term with the goal (or with entities/numbers
found in earlier relevant observations), or if the tool's topic domain (weather, math, files) matches the goal.
Only *runs* of >= drift_min_run irrelevant actions (or irrelevant actions followed by an irrelevant final
answer) are flagged, so one exploratory step is tolerated.
A pluggable embedding similarity is the obvious production upgrade; this baseline is lexical.
"""
from __future__ import annotations

import re
from typing import List, Set

from ..models import Finding, Trace
from ..textutil import arg_text, content_terms
from .base import Detector

DOMAIN_WORDS = {
    "weather": {"weather", "temperature", "forecast", "rain", "humidity", "hot", "hotter", "cold", "colder", "climate",
                "wind", "sunny", "celsius", "fahrenheit", "warm", "cool"},
    "math": {"calculate", "sum", "percent", "multiply", "divide", "product", "total", "average", "plus", "minus",
             "times", "ratio", "larger", "bigger", "difference", "many", "much"},
    "files": {"file", "csv", "document", "report", "read", "sales", "data"},
}


def _entities(text: str) -> Set[str]:
    ents = {m.lower() for m in re.findall(r"\b[A-Z][a-z]{2,}\b", text or "")}
    ents |= {n.replace(",", "") for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text or "")}
    return ents


class GoalDriftDetector(Detector):
    mode = "goal_drift"

    def detect(self, trace: Trace) -> List[Finding]:
        goal_terms = content_terms(trace.goal)
        goal_domains = {d for d, ws in DOMAIN_WORDS.items()
                        if goal_terms & {w for w in ws} or (d == "math" and re.search(r"\d.*\d|%", trace.goal))}
        carried: Set[str] = set()
        flags = []   # (step, off_topic?)
        for s in trace.steps:
            if s.is_action:
                terms = content_terms(arg_text(s.arguments))
                dom = self.cfg.registry.get(s.tool).domain if s.tool in self.cfg.registry else None
                if not terms and not dom:
                    rel = None                       # neutral (e.g. empty args)
                else:
                    rel = bool(terms & (goal_terms | carried)) or (dom in goal_domains) or (not terms and dom in goal_domains)
                flags.append((s, rel is False, rel is None))
                if rel:
                    carried |= _entities(s.observation)
        findings: List[Finding] = []
        i = 0
        while i < len(flags):
            if flags[i][1]:
                j = i
                while j < len(flags) and flags[j][1]:
                    j += 1
                run = flags[i:j]
                if len(run) >= self.cfg.drift_min_run:
                    findings.append(Finding(self.mode, [f[0].id for f in run],
                                            "high" if len(run) >= 3 else "medium", min(0.95, 0.6 + 0.1 * len(run)),
                                            f"{len(run)} consecutive actions unrelated to the goal "
                                            f"({', '.join(sorted({f[0].tool for f in run}))})."))
                i = j
            else:
                i += 1
        fin = trace.final_step
        if fin and fin.answer and goal_terms and any(f[1] for f in flags):
            a_terms = content_terms(fin.answer)
            if not (a_terms & (goal_terms | carried)) and len(a_terms) >= 3:
                findings.append(Finding(self.mode, [fin.id], "medium", 0.65,
                                        "Final answer does not address the stated goal."))
        return findings
