"""Human-readable outputs: a self-contained HTML dashboard (no external assets) and a Markdown summary."""
from __future__ import annotations

import html
from typing import Dict

from .models import FAILURE_MODES

CSS = """:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--card:#f5f6f8;--bd:#d9dce1;--ok:#1a7f37;--warn:#b7791f;--bad:#c62828;--acc:#2f5fd0}
@media(prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8e8e8;--mut:#9aa0a6;--card:#1f2226;--bd:#33373d;--ok:#4cc26b;--warn:#e0a93b;--bad:#ef6b6b;--acc:#7aa2ff}}
body{font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1100px;margin:0 auto;padding:24px}
h1{margin:0 0 4px}h2{margin-top:32px;border-bottom:1px solid var(--bd);padding-bottom:4px}.mut{color:var(--mut)}
.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:10px 16px;min-width:130px}
.card b{font-size:22px;display:block}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--bd);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600}.PASS{color:var(--ok)}.WARN{color:var(--warn)}.FAIL{color:var(--bad)}.bar{display:inline-block;height:8px;background:var(--acc);border-radius:4px;vertical-align:middle}
.tag{display:inline-block;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:0 8px;margin:1px;font-size:12px}.tag.miss{border-color:var(--bad);color:var(--bad)}
details{border:1px solid var(--bd);border-radius:8px;margin:6px 0;padding:6px 12px}summary{cursor:pointer}.step{padding:4px 8px;border-left:3px solid var(--bd);margin:4px 0;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap}
.step.flag{border-left-color:var(--bad);background:color-mix(in srgb,var(--bad) 10%,transparent)}"""


def _p(x):
    return "n/a" if x is None else f"{x:.2f}"


def _metric_table(m: Dict) -> str:
    rows = ["<table><tr><th>Failure mode</th><th>Support</th><th>TP</th><th>FP</th><th>FN</th><th>Precision (95% CI)</th><th>Recall (95% CI)</th><th>F1</th></tr>"]
    for mode in FAILURE_MODES:
        x = m[mode]
        ci = lambda c: "" if c[0] is None else f" [{c[0]:.2f}–{c[1]:.2f}]"
        rows.append(f"<tr><td>{mode}</td><td>{x['support']}</td><td>{x['tp']}</td><td>{x['fp']}</td><td>{x['fn']}</td>"
                    f"<td>{_p(x['precision'])}{ci(x['precision_ci'])}</td><td>{_p(x['recall'])}{ci(x['recall_ci'])}</td><td>{_p(x['f1'])} "
                    f"<span class='bar' style='width:{int((x['f1'] or 0) * 80)}px'></span></td></tr>")
    u = m["_micro"]
    rows.append(f"<tr><th>micro-avg</th><td></td><td>{u['tp']}</td><td>{u['fp']}</td><td>{u['fn']}</td><td>{_p(u['precision'])}</td><td>{_p(u['recall'])}</td><td>{_p(u['f1'])}</td></tr></table>")
    return "".join(rows)


def dashboard_html(res: Dict) -> str:
    o, tl = res["overall"], res["overall"]["_trace_level"]
    sl = res["slices"]
    h = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Agent Monitoring Dashboard</title><style>{CSS}</style></head><body>",
         "<h1>Agent Monitoring Dashboard</h1><p class='mut'>Deterministic, explainable detectors over agent traces. Score 100 = clean.</p><div class='cards'>"]
    for label, val in [("Traces", res["n_traces"]), ("Unhealthy (labelled)", tl["n_unhealthy"]),
                       ("Unhealthy caught (WARN/FAIL)", f"{tl['unhealthy_status_fail_or_warn']}/{tl['n_unhealthy']}"),
                       ("Healthy false alarms (WARN/FAIL)", f"{tl['healthy_status_fail_or_warn']}/{tl['n_healthy']}"),
                       ("Step localisation", _p(o["_localisation"]["accuracy"]))]:
        h.append(f"<div class='card'><span class='mut'>{label}</span><b>{val}</b></div>")
    h.append("</div>")
    for key, title in [("split=test", "Held-out test set (headline numbers)"), ("split=dev", "Dev set (used while building detectors — optimistic)")]:
        if key in sl:
            h.append(f"<h2>{title} — n={sl[key]['n']}</h2>{_metric_table(sl[key])}")
    if "difficulty=hard" in sl:
        h.append(f"<h2>Hard cases only — n={sl['difficulty=hard']['n']}</h2>{_metric_table(sl['difficulty=hard'])}")
    h.append("<h2>Misses and false alarms</h2>")
    if res["errors"]:
        h.append("<table><tr><th>Trace</th><th>Split</th><th>Mode</th><th>Type</th><th>Why / note</th></tr>")
        for e in res["errors"]:
            h.append(f"<tr><td>{html.escape(e['trace_id'])}</td><td>{e['split']}</td><td>{e['mode']}</td><td><span class='tag miss'>{e['type']}</span></td>"
                     f"<td>{html.escape(' '.join(e['detail']) or e['note'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p>None.</p>")
    h.append("<h2>Per-trace reports</h2><p class='mut'>Click a trace to see its steps; flagged steps are highlighted.</p>")
    rows = {r["trace_id"]: r["trace"] for r in res["_rows"]}
    for t in sorted(res["traces"], key=lambda x: x["score"]):
        flagged = {s for f in t["findings"] for s in f["step_ids"]}
        tr = rows[t["trace_id"]]
        h.append(f"<details><summary><b>{html.escape(t['trace_id'])}</b> — <span class='{t['status']}'>{t['status']}</span> score {t['score']} "
                 + "".join(f"<span class='tag'>{html.escape(m)}</span>" for m in sorted({f['mode'] for f in t['findings']}))
                 + f"<br><span class='mut'>Goal: {html.escape(t['goal'])}</span></summary>")
        if t["findings"]:
            h.append("<ul>" + "".join(f"<li><b>{f['mode']}</b> ({f['severity']}, conf {f['confidence']}) steps {f['step_ids']}: {html.escape(f['message'])}</li>" for f in t["findings"]) + "</ul>")
        else:
            h.append("<p>No issues detected.</p>")
        if t["labels"]:
            h.append(f"<p class='mut'>Ground-truth labels: {', '.join(t['labels'])}</p>")
        for s in tr.steps:
            body = f"{s.id}. " + (f"CALL {s.tool}({html.escape(str(s.arguments))}) → {html.escape(s.observation[:160])}" if s.is_action
                                  else f"ANSWER: {html.escape(s.answer or '')}")
            h.append(f"<div class='step{' flag' if s.id in flagged else ''}'>{body}</div>")
        h.append("</details>")
    h.append("</body></html>")
    return "\n".join(h)


def markdown_summary(res: Dict) -> str:
    out = ["# Monitoring report\n"]
    for key in ("split=test", "split=dev"):
        if key in res["slices"]:
            m = res["slices"][key]
            out.append(f"## {key} (n={m['n']})\n\n| mode | support | precision | recall | F1 |\n|---|---|---|---|---|")
            for mode in FAILURE_MODES:
                x = m[mode]
                out.append(f"| {mode} | {x['support']} | {_p(x['precision'])} | {_p(x['recall'])} | {_p(x['f1'])} |")
            out.append("")
    return "\n".join(out)
