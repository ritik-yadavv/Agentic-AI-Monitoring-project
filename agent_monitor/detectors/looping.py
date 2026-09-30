"""Looping / repetition: the agent keeps doing the same thing and gets the same result.

Three sub-detectors:
  * repeat runs  - same tool + (near-)same arguments N times in a row AND the observation never changes
  * cycles       - A,B,A,B,A,B ... with no change in the observations
  * runaway      - trace hits the step budget without ever producing a final answer

"No progress" (identical observations) is what separates a loop from legitimate polling or a
single retry after a transient error.
"""
from __future__ import annotations

from typing import List

from ..models import Finding, Step, Trace
from ..textutil import canon_args, content_terms, arg_text, norm_text, overlap_coeff
from .base import Detector


def _similar_call(a: Step, b: Step) -> bool:
    if a.tool != b.tool:
        return False
    if canon_args(a.arguments) == canon_args(b.arguments):
        return True
    return overlap_coeff(content_terms(arg_text(a.arguments)), content_terms(arg_text(b.arguments))) >= 0.75


def _same_obs(a: Step, b: Step) -> bool:
    return norm_text(a.observation) == norm_text(b.observation)


class LoopDetector(Detector):
    mode = "looping"

    def detect(self, trace: Trace) -> List[Finding]:
        calls = [s for s in trace.steps if s.is_action]
        return self._repeat_runs(calls) + self._cycles(calls) + self._runaway(trace)

    def _repeat_runs(self, calls: List[Step]) -> List[Finding]:
        out, i = [], 0
        while i < len(calls):
            j = i + 1
            while j < len(calls) and _similar_call(calls[i], calls[j]) and _same_obs(calls[i], calls[j]):
                j += 1
            n = j - i
            if n >= self.cfg.loop_min_repeat:
                conf = min(0.99, 0.85 + 0.03 * (n - self.cfg.loop_min_repeat))
                out.append(Finding(self.mode, [s.id for s in calls[i:j]], "high", conf,
                                   f"Tool '{calls[i].tool}' was called {n} times in a row with the same arguments "
                                   f"and an unchanged observation (no progress)."))
            i = max(j, i + 1)
        return out

    def _cycles(self, calls: List[Step]) -> List[Finding]:
        out, i = [], 0
        sigs = [(c.tool, canon_args(c.arguments)) for c in calls]
        while i < len(calls):
            found = False
            for p in (2, 3):
                if i + 3 * p > len(calls) or len(set(sigs[i:i + p])) != p:
                    continue
                end = i + p
                while end < len(calls) and sigs[end] == sigs[end - p] and _same_obs(calls[end], calls[end - p]):
                    end += 1
                reps = (end - i) // p
                if reps >= 3:
                    out.append(Finding(self.mode, [s.id for s in calls[i:end]], "high",
                                       min(0.97, 0.80 + 0.04 * reps),
                                       f"The agent cycles through {p} distinct calls "
                                       f"({', '.join(sorted({c.tool for c in calls[i:i + p]}))}) {reps} times "
                                       f"without any change in observations."))
                    i, found = end, True
                    break
            if not found:
                i += 1
        return out

    def _runaway(self, trace: Trace) -> List[Finding]:
        if trace.final_step is None and len(trace.steps) >= self.cfg.max_steps:
            return [Finding(self.mode, [trace.steps[-1].id], "medium", 0.7,
                            f"Step budget ({self.cfg.max_steps}) exhausted without a final answer.")]
        return []
