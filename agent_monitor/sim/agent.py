"""A small self-built tool-using agent. Its 'brain' is a deterministic planner (no LLM/API needed) behind a
Policy interface, so a real LLM policy can be dropped in. It runs a genuine act/observe loop against the
simulated ToolEnvironment; traces are the captured behaviour."""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..models import Step, Trace
from .environment import CITIES, COUNTRIES, ToolEnvironment, fmt, temp_of, cond_of


@dataclass
class Action:
    thought: str = ""
    tool: Optional[str] = None
    args: Any = field(default_factory=dict)
    answer: Optional[str] = None
    fault: Optional[str] = None          # ground-truth tag set only by fault-injecting wrappers


History = List[Tuple[Action, str]]


def _key(a: Action):
    return (a.tool, json.dumps(a.args, sort_keys=True, default=str))


class Task:
    """Healthy planner for one goal template."""
    kind = ""

    def __init__(self, goal: str, **p):
        self.goal, self.p = goal, p

    def plan_call(self, ok: List[str]) -> Optional[Tuple[str, str, dict]]:
        raise NotImplementedError

    def compose(self, ok: List[str]) -> str:
        raise NotImplementedError

    def next_action(self, history: History) -> Action:
        if history:
            last, obs = history[-1]
            if obs.startswith("ERROR: 503"):
                n = 0
                for a, o in reversed(history):
                    if o.startswith("ERROR: 503"):
                        n += 1
                    else:
                        break
                if n <= 1:
                    return Action("The tool is temporarily unavailable; I will retry once.", last.tool, last.args)
                return Action("The tool keeps failing.", answer=f"Sorry, I could not complete this: the {last.tool} service is unavailable.")
        ok, seen = [], set()
        for a, o in history:
            if a.tool and not a.fault and not o.startswith("ERROR") and _key(a) not in seen:
                seen.add(_key(a))
                ok.append(o)
        call = self.plan_call(ok)
        if call is None:
            return Action("I have everything I need.", answer=self.compose(ok))
        return Action(*call[:1], call[1], call[2])


class WeatherTask(Task):
    def plan_call(self, ok):
        return None if ok else (f"I need the current weather in {self.p['city']}.", "weather", {"city": self.p["city"]})
    def compose(self, ok):
        return f"It is {temp_of(self.p['city'])} C and {cond_of(self.p['city'])} in {self.p['city']}."


class CompareTask(Task):
    def plan_call(self, ok):
        c = [self.p["a"], self.p["b"]]
        return None if len(ok) >= 2 else (f"I need the weather in {c[len(ok)]}.", "weather", {"city": c[len(ok)]})
    def compose(self, ok):
        a, b = self.p["a"], self.p["b"]
        hot, cold = (a, b) if temp_of(a) > temp_of(b) else (b, a)
        return f"{hot} is hotter: {temp_of(hot)} C versus {temp_of(cold)} C in {cold}."


class MathTask(Task):
    def plan_call(self, ok):
        return None if ok else ("I'll compute this with the calculator.", "calculator",
                                {"expression": f"{self.p['pct']}/100*{self.p['n']}"})
    def compose(self, ok):
        return f"{self.p['pct']}% of {self.p['n']} is {ok[0]}."


class CapitalTask(Task):
    def plan_call(self, ok):
        return None if ok else (f"I'll search for the capital of {self.p['country']}.", "search",
                                {"query": f"capital of {self.p['country']}"})
    def compose(self, ok):
        return f"The capital of {self.p['country']} is {COUNTRIES[self.p['country']][0]}."


class RatioTask(Task):
    def plan_call(self, ok):
        c = [self.p["a"], self.p["b"]]
        if len(ok) < 2:
            return (f"I need the population of {c[len(ok)]}.", "search", {"query": f"population of {c[len(ok)]}"})
        if len(ok) == 2:
            a, b = [re.search(r"about ([\d.]+) million", o).group(1) for o in ok]
            return ("Now divide the two populations.", "calculator", {"expression": f"{a}/{b}"})
        return None
    def compose(self, ok):
        return f"{self.p['a']} has about {ok[2]} times the population of {self.p['b']}."


class FileTask(Task):
    def plan_call(self, ok):
        if not ok:
            return ("I'll read the sales file.", "read_file", {"path": "/workspace/data/sales.csv"})
        if len(ok) == 1:
            nums = re.findall(r"^Q\d,(\d+)", ok[0], re.M)
            return ("Add up the quarterly revenue.", "calculator", {"expression": "+".join(nums)})
        return None
    def compose(self, ok):
        return f"Total sales across the quarters are {ok[1]}."


TASK_KINDS = ["weather", "compare", "math", "capital", "ratio", "file"]


def make_task(kind: str, rng: random.Random) -> Task:
    if kind == "weather":
        c = rng.choice(CITIES)
        return WeatherTask(rng.choice([f"What's the weather in {c}?", f"How is the weather in {c} right now?"]), city=c)
    if kind == "compare":
        while True:
            a, b = rng.sample(CITIES, 2)
            if temp_of(a) != temp_of(b):
                return CompareTask(f"Which city is hotter right now, {a} or {b}?", a=a, b=b)
    if kind == "math":
        pct, n = rng.choice([5, 10, 15, 20, 25, 30]), rng.choice([120, 240, 360, 480, 850])
        return MathTask(f"What is {pct}% of {n}?", pct=pct, n=n)
    if kind == "capital":
        c = rng.choice(list(COUNTRIES))
        return CapitalTask(f"What is the capital of {c}?", country=c)
    if kind == "ratio":
        a, b = sorted(rng.sample(list(COUNTRIES), 2), key=lambda c: -COUNTRIES[c][1])
        return RatioTask(f"How many times larger is the population of {a} than that of {b}?", a=a, b=b)
    return FileTask("What are the total sales in /workspace/data/sales.csv?")


def run_agent(goal: str, policy, env: ToolEnvironment, trace_id: str, max_steps: int = 12):
    """Real act/observe loop. Returns (Trace, fault_steps)."""
    history: History = []
    steps, faults = [], {}
    for i in range(1, max_steps + 1):
        act = policy.next_action(history)
        if act.answer is not None:
            steps.append(Step(id=i, thought=act.thought, answer=act.answer))
        else:
            obs = env.call(act.tool, act.args)
            history.append((act, obs))
            steps.append(Step(id=i, thought=act.thought, tool=act.tool, arguments=act.args, observation=obs))
        for f in (act.fault.split(",") if act.fault else []):
            faults.setdefault(f, []).append(i)
        if act.answer is not None:
            break
    return Trace(trace_id=trace_id, goal=goal, steps=steps), faults
