"""Trace ingestion: JSON files, directories, and raw ReAct-style text logs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Union

from .models import Step, Trace


class TraceFormatError(ValueError):
    pass


_STEP_KEYS = {"id", "thought", "tool", "arguments", "observation", "answer"}


def trace_from_dict(data: dict, source: str = "<dict>") -> Trace:
    if not isinstance(data, dict):
        raise TraceFormatError(f"{source}: trace must be a JSON object")
    for key in ("trace_id", "goal", "steps"):
        if key not in data:
            raise TraceFormatError(f"{source}: missing required key '{key}'")
    if not isinstance(data["steps"], list):
        raise TraceFormatError(f"{source}: 'steps' must be a list")
    steps: List[Step] = []
    last_id = 0
    for i, raw in enumerate(data["steps"]):
        if not isinstance(raw, dict):
            raise TraceFormatError(f"{source}: step #{i} must be an object")
        raw = {k: v for k, v in raw.items() if k in _STEP_KEYS}
        raw.setdefault("id", last_id + 1)
        if not isinstance(raw["id"], int) or raw["id"] <= last_id:
            raise TraceFormatError(f"{source}: step ids must be strictly increasing integers (step #{i})")
        last_id = raw["id"]
        if "observation" in raw and not isinstance(raw["observation"], str):
            raw["observation"] = json.dumps(raw["observation"])
        steps.append(Step(**raw))
    return Trace(
        trace_id=str(data["trace_id"]),
        goal=str(data["goal"]),
        steps=steps,
        labels={k: bool(v) for k, v in data.get("labels", {}).items()},
        fault_steps={k: list(v) for k, v in data.get("fault_steps", {}).items()},
        meta=dict(data.get("meta", {})),
    )


def load_trace(path: Union[str, Path]) -> Trace:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TraceFormatError(f"{p}: invalid JSON ({e})") from e
    return trace_from_dict(data, str(p))


def load_traces(root: Union[str, Path]) -> List[Trace]:
    """Load one file, or every *.json under a directory (recursive, sorted)."""
    root = Path(root)
    paths: Iterable[Path] = [root] if root.is_file() else sorted(root.rglob("*.json"))
    traces = []
    for p in paths:
        t = load_trace(p)
        if "split" not in t.meta and root.is_dir():
            rel = p.relative_to(root).parts
            t.meta["split"] = rel[0] if len(rel) > 1 else "all"
        traces.append(t)
    return traces


def save_trace(trace: Trace, path: Union[str, Path]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(trace.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


_REACT = re.compile(r"^(Thought|Action|Action Input|Observation|Final Answer)\s*:\s*(.*)$", re.I)


def parse_react_log(text: str, trace_id: str = "react", goal: str = "") -> Trace:
    """Parse a classic ReAct transcript (Thought/Action/Action Input/Observation/Final Answer)."""
    steps: List[Step] = []
    cur: dict = {}
    field_name = None

    def flush():
        nonlocal cur
        if cur:
            args = cur.get("arguments", "")
            if isinstance(args, str) and args.strip():
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"input": args.strip()}
            elif isinstance(args, str):
                args = {}
            steps.append(Step(id=len(steps) + 1, thought=cur.get("thought", "").strip(), tool=cur.get("tool"),
                              arguments=args, observation=cur.get("observation", "").strip(),
                              answer=cur.get("answer")))
        cur = {}

    for line in text.splitlines():
        m = _REACT.match(line.strip())
        if m:
            key, val = m.group(1).lower(), m.group(2)
            if key == "thought" and cur:
                flush()
            field_name = {"thought": "thought", "action": "tool", "action input": "arguments",
                          "observation": "observation", "final answer": "answer"}[key]
            cur[field_name] = val.strip() if field_name in ("tool", "answer") else val
        elif field_name and line.strip():
            cur[field_name] = (cur.get(field_name, "") + "\n" + line.strip()) if cur.get(field_name) else line.strip()
    flush()
    if not goal:
        m = re.search(r"(?im)^(?:question|goal|task)\s*:\s*(.+)$", text)
        goal = m.group(1).strip() if m else ""
    return Trace(trace_id=trace_id, goal=goal, steps=steps)
