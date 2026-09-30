"""Tool misuse: unknown tools, schema violations, and nonsensical argument values."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import Finding, Step, Trace
from .base import Detector

_PLACEHOLDERS = {"", "none", "null", "undefined", "todo", "tbd", "query", "<query>", "???", "...", "n/a", "string"}


def _type_ok(val: Any, t: str) -> bool:
    if t == "string":
        return isinstance(val, str)
    if t == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if t == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if t == "boolean":
        return isinstance(val, bool)
    if t == "object":
        return isinstance(val, dict)
    if t == "array":
        return isinstance(val, list)
    return True


def _semantic_issues(tool: str, args: Dict[str, Any]) -> List[str]:
    """Value-level checks for arguments that are the right *type* but make no sense."""
    issues = []
    if tool == "calculator":
        e = args.get("expression")
        if isinstance(e, str):
            if not re.fullmatch(r"[0-9+\-*/().%^\s,]+", e) or not re.search(r"\d", e):
                issues.append(f"expression {e!r} is not a valid arithmetic expression")
            elif e.count("(") != e.count(")"):
                issues.append("unbalanced parentheses in expression")
    elif tool == "weather":
        c = args.get("city")
        if isinstance(c, str) and not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{1,48}", c.strip()):
            issues.append(f"city {c!r} is not a plausible place name")
    elif tool == "search":
        q = args.get("query")
        if isinstance(q, str):
            if q.strip().lower() in _PLACEHOLDERS or not re.search(r"[A-Za-z0-9]{2}", q):
                issues.append(f"query {q!r} is empty or a placeholder")
    elif tool == "send_email":
        to = args.get("to")
        if isinstance(to, str) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to.strip()):
            issues.append(f"recipient {to!r} is not an email address")
    elif tool in ("read_file", "write_file"):
        p = args.get("path")
        if isinstance(p, str) and (not p.strip() or "\x00" in p):
            issues.append("path is empty or contains a NUL byte")
    elif tool == "shell":
        c = args.get("command")
        if isinstance(c, str) and not c.strip():
            issues.append("empty command")
    return issues


class ToolMisuseDetector(Detector):
    mode = "tool_misuse"

    def detect(self, trace: Trace) -> List[Finding]:
        out = []
        for s in trace.steps:
            if not s.is_action:
                continue
            f = self._check(s)
            if f:
                out.append(f)
        return out

    def _check(self, s: Step):
        spec = self.cfg.registry.get(s.tool)
        bump = 0.02 if s.is_error else 0.0     # the tool itself rejected the call: extra corroboration
        if spec is None:
            return Finding(self.mode, [s.id], "high", min(0.99, 0.93 + bump),
                           f"Call to unknown tool '{s.tool}' (not in the tool registry).")
        args = s.arguments
        if not isinstance(args, dict):
            return Finding(self.mode, [s.id], "high", min(0.99, 0.95 + bump),
                           f"Arguments for '{s.tool}' must be an object, got {type(args).__name__}.")
        problems, severity, conf = [], "medium", 0.80
        missing = [k for k, p in spec.params.items() if p.required and k not in args]
        if missing:
            problems.append("missing required: " + ", ".join(missing))
            severity, conf = "high", 0.96
        wrong = [k for k, p in spec.params.items() if k in args and not _type_ok(args[k], p.type)]
        if wrong:
            problems.append("wrong type: " + ", ".join(f"{k} (expected {spec.params[k].type})" for k in wrong))
            severity, conf = "high", 0.95
        unexpected = [k for k in args if k not in spec.params]
        if unexpected:
            problems.append("unexpected argument(s): " + ", ".join(unexpected))
            if not problems[:-1]:
                severity, conf = "low", 0.70
        for k, p in spec.params.items():
            v = args.get(k)
            if isinstance(v, str) and k not in wrong:
                if p.max_len and len(v) > p.max_len:
                    problems.append(f"{k} longer than {p.max_len} chars")
                if p.enum and v not in p.enum:
                    problems.append(f"{k} not one of {list(p.enum)}")
        if not missing and not wrong:
            sem = _semantic_issues(s.tool, args)
            if sem:
                problems += sem
                severity, conf = "medium", 0.82
        if not problems:
            return None
        return Finding(self.mode, [s.id], severity, min(0.99, conf + bump),
                       f"Malformed call to '{s.tool}': " + "; ".join(problems) + ".")
