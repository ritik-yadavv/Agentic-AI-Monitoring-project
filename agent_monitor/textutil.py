"""Small dependency-free text helpers shared by the detectors."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Set

_TOKEN = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?|[A-Za-z][A-Za-z'\-]*")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")

STOPWORDS = frozenset("""
a an the and or but if then than so of to in on at by for with from into onto over under about as is are was were be been being
am do does did doing have has had having i me my we our you your it its this that these those there here what which who whom
whose when where why how can could should would will shall may might must not no yes please tell find get give show let
me us them they he she his her their also just only very more most some any all each both other such own same too
current currently latest today now need needs want wants use using used call calling check checking look looking first next
then now step answer result results tool tools information info make sure will going gonna
""".split())


def stem(word: str) -> str:
    w = word.lower().replace("'s", "").strip("'-")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def content_terms(text: str) -> Set[str]:
    """Stemmed non-stopword terms (numbers included, commas removed)."""
    out: Set[str] = set()
    for tok in _TOKEN.findall(text or ""):
        if tok[0].isdigit():
            out.add(tok.replace(",", ""))
            continue
        if tok.lower() in STOPWORDS:
            continue
        s = stem(tok)
        if len(s) >= 3 and s not in STOPWORDS:
            out.add(s)
    return out


def numbers(text: str) -> List[float]:
    vals = []
    for m in _NUMBER.findall(text or ""):
        try:
            vals.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return vals


def string_leaves(obj: Any) -> Iterable[str]:
    """All strings and numbers inside a JSON-like structure, as text."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from string_leaves(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from string_leaves(v)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        yield str(obj)
    else:
        yield str(obj)


def arg_text(args: Any) -> str:
    return " ".join(string_leaves(args))


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def canon_args(args: Any) -> str:
    """Canonical string form of tool arguments (order/case/whitespace-insensitive)."""
    if isinstance(args, dict):
        items = sorted((str(k), norm_text(v) if isinstance(v, str) else v) for k, v in args.items())
        return json.dumps(items, default=str, sort_keys=True)
    return norm_text(json.dumps(args, default=str))


def overlap_coeff(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
