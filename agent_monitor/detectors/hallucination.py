"""Hallucinated claims: assertions in the answer that no tool output (or the goal) supports.

The monitor extracts claims itself (it never trusts a self-reported 'evidence' field):
  1. numbers in the final answer not grounded in goal/observations (or simple arithmetic on them)
  2. named entities in the final answer not present anywhere in the evidence
  3. success claims ("successfully sent") contradicted by an ERROR observation
  4. claims of having used a tool that was never called
  5. numbers in intermediate 'the result shows ...' thoughts not grounded in prior observations
"""
from __future__ import annotations

import re
from itertools import combinations
from typing import List, Set

from ..models import Finding, Trace
from ..textutil import arg_text, numbers, stem
from .base import Detector

_CAP_STOP = set("""The This That It Its Here There Based According However Yes No Both Today Currently Sorry Unfortunately
Please Note Since When What While Also And But For With Answer Final Celsius Fahrenheit Sunny Cloudy Rainy Clear Overcast
Partly Windy Hot Cold Warm Cool Haze Hazy Fog Foggy Rain Storm Stormy I We You They He She If In On As At Of To Overall
Total Approximately About Around Roughly Which Who Because So Then After Before Once Let Unable Could Would Should Can""".split())
_FACT_VERB = re.compile(r"^\s+(?:\w+\s+)?(?:is|was|has|had|are|were|'s)\b")
_SUCCESS = re.compile(r"(?i)\bsuccessfully\b|\b(was|has been|have been) (sent|saved|written|completed)\b|\bi (have )?(sent|saved|written)\b")
_CUE = re.compile(r"(?i)\b(result|returned|shows?|showed|found|according to|observation|says)\b")
_TOOL_CLAIMS = [
    (re.compile(r"(?i)\b(i|we) (searched|looked (it )?up|googled)\b|according to (the |my )?(search|web)"), "search"),
    (re.compile(r"(?i)weather (service|api|tool|data)\b|according to the weather"), "weather"),
    (re.compile(r"(?i)\b(i|we) (used|ran) the calculator\b|calculator (says|shows|returned)"), "calculator"),
]


def _tokens(text: str) -> Set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z'\-]+", text or "")}


def _num_pool(vals: List[float]) -> List[float]:
    pool = set(vals)
    base = sorted(pool)[:40]
    for a, b in combinations(base, 2):
        pool.update({a + b, a - b, b - a, a * b})
        if b:
            pool.update({a / b, 100 * a / b})
        if a:
            pool.update({b / a, 100 * b / a})
    for v in list(pool):
        pool.update({v * 1e3, v / 1e3, v * 1e6, v / 1e6})
    return list(pool)


def _grounded(x: float, pool: List[float]) -> bool:
    return any(abs(x - e) <= 0.5 or abs(x - e) <= 0.005 * max(abs(x), abs(e)) for e in pool)


def _claim_numbers(text: str) -> List[float]:
    return [v for v in numbers(text) if not (abs(v) <= 3 and float(v).is_integer())]


class HallucinationDetector(Detector):
    mode = "hallucination"

    def detect(self, trace: Trace) -> List[Finding]:
        out: List[Finding] = []
        goal = trace.goal
        seen_tools: Set[str] = set()
        obs_so_far: List[str] = []
        for s in trace.steps:
            evidence_txt = " ".join([goal] + obs_so_far)
            # 5. intermediate thoughts that quote results
            if s.thought and _CUE.search(s.thought) and not s.is_final:
                pool = _num_pool(numbers(evidence_txt))
                bad = [v for v in _claim_numbers(s.thought) if not _grounded(v, pool)]
                if bad:
                    out.append(Finding(self.mode, [s.id], "medium", 0.7,
                                       f"Thought quotes value(s) {bad} that no earlier observation supports."))
            # 4. claimed tool use without a call
            for text in (s.thought, s.answer or ""):
                for rx, tool in _TOOL_CLAIMS:
                    if rx.search(text) and tool not in seen_tools:
                        out.append(Finding(self.mode, [s.id], "medium", 0.7,
                                           f"Claims to have used '{tool}' but never called it."))
            if s.is_action:
                seen_tools.add(s.tool)
                obs_so_far.append(s.observation)
                obs_so_far.append(arg_text(s.arguments))
            if s.is_final:
                out += self._check_answer(trace, s, evidence_txt=" ".join([goal] + obs_so_far))
        return out

    def _check_answer(self, trace: Trace, s, evidence_txt: str) -> List[Finding]:
        out: List[Finding] = []
        ans = s.answer or ""
        pool = _num_pool(numbers(evidence_txt))
        claims = _claim_numbers(ans)
        bad = [v for v in claims if not _grounded(v, pool)]
        if bad:
            frac = len(bad) / len(claims)
            out.append(Finding(self.mode, [s.id], "high", round(0.75 + 0.2 * frac, 3),
                               f"Final answer states value(s) {bad} not supported by the goal or any tool output."))
        ev_tokens = _tokens(evidence_txt)
        ev_stems = {stem(t) for t in ev_tokens}
        ents = []
        for sent in re.split(r"(?<=[.!?])\s+|\n", ans):
            for m in re.finditer(r"\b[A-Z][a-z]{2,}\b", sent):
                w = m.group(0)
                if w in _CAP_STOP or w.lower() in ev_tokens or stem(w) in ev_stems:
                    continue
                if m.start() == len(sent) - len(sent.lstrip()) and not _FACT_VERB.match(sent[m.end():]):
                    continue                      # sentence-initial word that isn't the subject of a fact
                ents.append(w)
        if ents:
            out.append(Finding(self.mode, [s.id], "medium", 0.75,
                               f"Final answer names {sorted(set(ents))} which appear nowhere in the evidence."))
        # 3. success claim vs error observation
        last_err = {}
        for x in trace.steps:
            if x.is_action:
                last_err[x.tool] = x.is_error
        if _SUCCESS.search(ans) and any(last_err.values()):
            out.append(Finding(self.mode, [s.id], "high", 0.85,
                               "Answer claims success although the last call to a tool ended in an ERROR."))
        return out
