"""Core data model: a Trace is an ordered list of Steps (thought -> tool call -> observation)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FAILURE_MODES = ("looping", "tool_misuse", "hallucination", "goal_drift", "unsafe_action")
SEVERITIES = ("low", "medium", "high", "critical")


@dataclass
class Step:
    """One agent step.

    A step is either an *action* (``tool`` is set), a *final answer* (``answer`` is set),
    or a pure reasoning step (neither).  ``arguments`` is deliberately typed ``Any``: a
    malformed call (e.g. a list instead of an object) is data the monitor must be able to see.
    """

    id: int
    thought: str = ""
    tool: Optional[str] = None
    arguments: Any = field(default_factory=dict)
    observation: str = ""
    answer: Optional[str] = None

    @property
    def is_action(self) -> bool:
        return self.tool is not None

    @property
    def is_final(self) -> bool:
        return self.answer is not None

    @property
    def is_error(self) -> bool:
        return self.observation.strip().upper().startswith("ERROR")


@dataclass
class Trace:
    trace_id: str
    goal: str
    steps: List[Step]
    # Ground truth (only present on self-generated test traces).
    labels: Dict[str, bool] = field(default_factory=dict)
    fault_steps: Dict[str, List[int]] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def final_step(self) -> Optional[Step]:
        for s in reversed(self.steps):
            if s.is_final:
                return s
        return None

    def to_dict(self) -> Dict[str, Any]:
        steps = []
        for s in self.steps:
            d: Dict[str, Any] = {"id": s.id, "thought": s.thought}
            if s.tool is not None:
                d["tool"] = s.tool
                d["arguments"] = s.arguments
                d["observation"] = s.observation
            if s.answer is not None:
                d["answer"] = s.answer
            steps.append(d)
        out: Dict[str, Any] = {"trace_id": self.trace_id, "goal": self.goal, "steps": steps}
        if self.labels:
            out["labels"] = self.labels
        if self.fault_steps:
            out["fault_steps"] = self.fault_steps
        if self.meta:
            out["meta"] = self.meta
        return out


@dataclass
class Finding:
    mode: str
    step_ids: List[int]
    severity: str
    confidence: float
    message: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "step_ids": self.step_ids,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "message": self.message,
        }
