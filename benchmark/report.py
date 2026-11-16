"""Summarize benchmark records into tables, figures, and the README block.

    python3 benchmark/report.py benchmark/results/raw.jsonl [--readme README.md]

Relative cost weights uncached input 1, cache reads 0.1, cache writes 1.25 and
output 5, which is the usual shape of list prices; override with --prices.
Records that touched files outside their workspace are excluded.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BEGIN, END = "<!-- benchmark:begin -->", "<!-- benchmark:end -->"
COND_LABEL = {"baseline": "baseline", "context": "context-state"}
SUITE_TITLE = {"resume": "single resume in a new chat",
               "multiday": "four days, one new chat per day"}
COLORS = {"baseline": "#9aa5b1", "context": "#2f80ed"}


def load(paths: list[Path]) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["model"], r.get("scale", 1), r["suite"], r["condition"], r["rep"], r["task"])
            latest[key] = r
    versions = {r.get("fixture") for r in latest.values()}
    if len(versions) > 1:
        print(f"warning: records come from {len(versions)} fixture versions {sorted(map(str, versions))}; "
              "compare only runs from one version", file=sys.stderr)
    for r in latest.values():
        if r.get("outside_paths"):
            print(f'excluded {r["model"]} x{r.get("scale", 1)} {r["suite"]} {r["condition"]} '
                  f'{r["task"]} rep{r["rep"]}: read outside its workspace, '
                  f'e.g. {r["outside_paths"][0]}', file=sys.stderr)
    return [r for r in latest.values() if r["status"] == "finished" and r.get("usage")
            and not r.get("outside_paths")]


def cost(u: dict, prices: tuple[float, float, float, float]) -> float:
    p_in, p_read, p_write, p_out = prices
    uncached = max(u["input"] - u["cache_read"] - u["cache_write"], 0)
    return uncached * p_in + u["cache_read"] * p_read + u["cache_write"] * p_write + u["output"] * p_out


def load_prices(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    return json.loads(path.read_text())["models"]


def model_params(r: dict) -> dict[str, str]:
    """Model id and parameters: the spec on the command line, overridden by what the run used."""
    mid, _, spec = r["model"].partition(":")
    params = dict(p.split("=", 1) for p in spec.split(",") if "=" in p)
    res = r.get("model_resolved") or {}
    params.update(res.get("params") or {})
    params["id"] = res.get("id") or mid
    return params


def price_for(r: dict, table: list[dict]) -> dict | None:
    """Most specific price entry whose every key matches; None if the variant is unknown."""
    have = model_params(r)
    hits = [p for p in table if all(have.get(k) == v for k, v in p["match"].items())]
    return max(hits, key=lambda p: len(p["match"])) if hits else None


def usd(u: dict, p: dict) -> float:
    uncached = max(u["input"] - u["cache_read"] - u["cache_write"], 0)
    write = p["cache_write"] if p.get("cache_write") is not None else p["input"]
    return (uncached * p["input"] + u["cache_read"] * p["cache_read"]
            + u["cache_write"] * write + u["output"] * p["output"]) / 1e6


def mean_sd(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return float("nan"), 0.0
    return statistics.fmean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)


def k(x: float) -> str:
    return f"{x / 1000:.1f}K"


def pct(base: float, new: float) -> str:
    return f"{(1 - new / base) * 100:.0f}%" if base else "n/a"


def new_cell() -> dict:
    return {"tokens": [], "cost": [], "usd": [], "score": []}


PRICE_LABELS: dict[str, set[str]] = defaultdict(set)


def summarize(records: list[dict], prices, table: list[dict] | None = None) -> dict:
    """model -> scale -> suite -> task -> condition -> metric lists."""
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: defaultdict(lambda: defaultdict(new_cell)))))
    for r in records:
        cell = out[r["model"]][r.get("scale", 1)][r["suite"]][r["task"]][r["condition"]]
        cell["tokens"].append(r["usage"]["total"])
        cell["cost"].append(cost(r["usage"], prices))
        p = price_for(r, table or [])
        cell["usd"].append(usd(r["usage"], p) if p else None)
        PRICE_LABELS[r["model"]].add(p["label"] if p else "unknown variant")
        cell["score"].append(r["score"] / r["facts_total"] if r["facts_total"] else 1.0)
    return out


def dollars(cell: dict) -> float | None:
    vals = cell["usd"]
    return statistics.fmean(vals) if vals and None not in vals else None


def money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.3f}"


def suite_totals(tasks: dict) -> dict[str, dict[str, float]] | None:
    """Sum of per-task means for tasks that both conditions completed."""
    both = [t for t, c in tasks.items() if "baseline" in c and "context" in c]
    if not both:
        return None
    tot = {}
    for cond in COND_LABEL:
        cells = [tasks[t][cond] for t in both]
        usd_cells = [dollars(c) for c in cells]
        tot[cond] = {"tokens": sum(mean_sd(c["tokens"])[0] for c in cells),
                     "cost": sum(mean_sd(c["cost"])[0] for c in cells),
                     "usd": None if None in usd_cells else sum(usd_cells),
                     "score": statistics.fmean(mean_sd(c["score"])[0] for c in cells),
                     "n": min(len(c["tokens"]) for c in cells), "tasks": len(both)}
    return tot


def bootstrap_tokens(by_suite: dict) -> float | None:
    cell = by_suite.get("bootstrap", {}).get("B0-bootstrap", {}).get("context")
    return mean_sd(cell["tokens"])[0] if cell else None


def cost_cells(a: dict, b: dict) -> tuple[str, str]:
    """Dollar figures when the variant's price is known, else the weighted estimate (marked *)."""
    if a["usd"] is not None and b["usd"] is not None:
        return f"{money(a['usd'])} / {money(b['usd'])}", pct(a["usd"], b["usd"])
    return "n/a", pct(a["cost"], b["cost"]) + "*"


def scaling_table(summary: dict) -> str:
    lines = ["| model | project size | suite | baseline tokens | context-state tokens | "
             "token saving | cost (baseline / context-state) | cost saving | "
             "facts correct (baseline / context-state) | runs per task |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for model, scales in summary.items():
        for scale in sorted(scales):
            for suite in ("resume", "multiday"):
                tot = suite_totals(scales[scale].get(suite, {}))
                if not tot:
                    continue
                a, b = tot["baseline"], tot["context"]
                money_pair, saving = cost_cells(a, b)
                lines.append(f"| {name(model)} | x{scale} | {suite} | {k(a['tokens'])} | {k(b['tokens'])} | "
                             f"{pct(a['tokens'], b['tokens'])} | {money_pair} | {saving} | "
                             f"{a['score']:.0%} / {b['score']:.0%} | {min(a['n'], b['n'])} |")
    return "\n".join(lines)


def name(model: str) -> str:
    """Short display name: the list-price label when every run of the model has one."""
    labels = PRICE_LABELS.get(model, set())
    return next(iter(labels)) if len(labels) == 1 and "unknown variant" not in labels else model


def price_lines() -> list[str]:
    out = []
    for model, labels in PRICE_LABELS.items():
        if labels == {"unknown variant"}:
            out.append(f"- {model}: variant not recorded, so no dollar price; cost saving is the "
                       "weighted estimate (marked *).")
        else:
            out.append(f"- {name(model)} is `{model}`, priced as {', '.join(sorted(labels))}.")
    return out


def breakeven_lines(summary: dict) -> list[str]:
    out = []
    for model, scales in summary.items():
        for scale in sorted(scales):
            boot = bootstrap_tokens(scales[scale])
            tot = suite_totals(scales[scale].get("resume", {}))
            if boot is None or not tot:
                continue
            n = tot["baseline"]["tasks"]
            per = (tot["baseline"]["tokens"] - tot["context"]["tokens"]) / n
            boot_cell = scales[scale]["bootstrap"]["B0-bootstrap"]["context"]
            boot_usd = dollars(boot_cell)
            usd_note = ""
            if boot_usd is not None and tot["baseline"]["usd"] is not None:
                per_usd = (tot["baseline"]["usd"] - tot["context"]["usd"]) / n
                usd_note = f"; in dollars {money(boot_usd)} once, {money(per_usd)} saved per resume"
                if per_usd > 0:
                    usd_note += f", repaid after about {boot_usd / per_usd:.1f} resumes"
            if per > 0:
                out.append(f"- {name(model)} x{scale}: bootstrap {k(boot)} tokens, repaid after about "
                           f"{boot / per:.1f} resumes ({k(per)} saved per resume){usd_note}.")
            else:
                out.append(f"- {name(model)} x{scale}: bootstrap {k(boot)} tokens; resumes did not save "
                           f"tokens at this size, so it is not repaid.")
    return out


def task_table(summary: dict) -> str:
    lines = []
    for model, scales in summary.items():
        for scale in sorted(scales):
            for suite in ("resume", "multiday"):
                tasks = scales[scale].get(suite)
                if not tasks:
                    continue
                lines += ["", f"**{name(model)}, project x{scale}, {SUITE_TITLE[suite]}**", "",
                          "| task | baseline tokens | context-state tokens | token saving | "
                          "facts correct (baseline / context-state) |", "|---|---|---|---|---|"]
                for task, conds in tasks.items():
                    a, b = conds.get("baseline"), conds.get("context")
                    if not (a and b):
                        continue
                    ta, sa = mean_sd(a["tokens"])
                    tb, sb = mean_sd(b["tokens"])
                    lines.append(f"| {task} | {k(ta)} ± {k(sa)} | {k(tb)} ± {k(sb)} | {pct(ta, tb)} | "
                                 f"{mean_sd(a['score'])[0]:.0%} / {mean_sd(b['score'])[0]:.0%} |")
    return "\n".join(lines)


def tables(summary: dict) -> str:
    parts = ["Totals are sums of per-task means; savings are relative to baseline. Dollar costs "
             "use the Cursor list prices in `benchmark/prices.json`.", "",
             scaling_table(summary), "", *price_lines()]
    be = breakeven_lines(summary)
    if be:
        parts += ["", "One-time cost of writing the first STATE files:", "", *be]
    parts += ["", "<details><summary>Per-task results</summary>", task_table(summary), "",
              "</details>"]
    return "\n".join(parts)


def figures(summary: dict, outdir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    models = list(summary)

    priced = [m for m in models
              if all((t := suite_totals(summary[m][s].get(suite, {}))) is None
                     or t["baseline"]["usd"] is not None
                     for s in summary[m] for suite in ("resume", "multiday"))]
    if priced:
        fig, axes = plt.subplots(1, len(priced), figsize=(5.5 * len(priced), 3.8), squeeze=False)
        for ax, model in zip(axes[0], priced):
            scales = sorted(summary[model])
            width = 0.2
            for i, s in enumerate(scales):
                for j, (suite, cond) in enumerate([(su, c) for su in ("resume", "multiday")
                                                   for c in COND_LABEL]):
                    t = suite_totals(summary[model][s].get(suite, {}))
                    if not t:
                        continue
                    x = i + (j - 1.5) * width
                    y = t[cond]["usd"]
                    ax.bar(x, y, width, color=COLORS[cond], hatch="//" if suite == "multiday" else None,
                           edgecolor="white", label=f"{COND_LABEL[cond]}, "
                           f"{'one resume' if suite == 'resume' else 'four days'}" if i == 0 else None)
                    if cond == "context":
                        p = pct(t["baseline"]["usd"], y)
                        ax.annotate("+" + p[1:] if p.startswith("-") else "-" + p, (x, y),
                                    textcoords="offset points", xytext=(0, 2),
                                    ha="center", fontsize=7, color=COLORS[cond])
            ax.set_xticks(range(len(scales)), [f"x{s}" for s in scales])
            ax.set_xlabel("project size")
            ax.set_ylabel("cost per task set (USD, list price)")
            ax.set_title(name(model))
            ax.legend(frameon=False, fontsize=7)
        fig.tight_layout()
        made.append(save(fig, outdir / "cost.png", plt))

    fig, axes = plt.subplots(1, len(models), figsize=(5.5 * len(models), 3.8), squeeze=False)
    for ax, model in zip(axes[0], models):
        scales = sorted(summary[model])
        for suite, style in (("resume", "-"), ("multiday", "--")):
            pts = [(s, suite_totals(summary[model][s].get(suite, {}))) for s in scales]
            pts = [(s, t) for s, t in pts if t]
            if not pts:
                continue
            for cond in COND_LABEL:
                ax.plot([s for s, _ in pts], [t[cond]["tokens"] / 1000 for _, t in pts], style,
                        marker="o", color=COLORS[cond], label=f"{COND_LABEL[cond]}, {suite}")
            s, t = pts[-1]
            ax.annotate(pct(t["baseline"]["tokens"], t["context"]["tokens"]) + " saved",
                        (s, t["context"]["tokens"] / 1000), textcoords="offset points",
                        xytext=(6, 4), fontsize=8, color=COLORS["context"])
        ax.set_xticks(scales, [f"x{s}" for s in scales])
        ax.margins(x=0.2)
        ax.set_xlabel("project size")
        ax.set_ylabel("total tokens (K)")
        ax.set_title(name(model))
        ax.legend(frameon=False, fontsize=7, loc="best")
    fig.tight_layout()
    made.append(save(fig, outdir / "scaling.png", plt))

    fig, axes = plt.subplots(1, len(models), figsize=(5.5 * len(models), 3.6), squeeze=False)
    for ax, model in zip(axes[0], models):
        scale = max(summary[model])
        tasks = summary[model][scale].get("resume", {})
        names = [t for t in tasks if len(tasks[t]) == 2]
        width = 0.38
        for j, cond in enumerate(COND_LABEL):
            ms = [mean_sd(tasks[t][cond]["tokens"]) for t in names]
            ax.bar([i + (j - 0.5) * width for i in range(len(names))], [m / 1000 for m, _ in ms],
                   width, yerr=[s / 1000 for _, s in ms], color=COLORS[cond],
                   label=COND_LABEL[cond], capsize=3)
        ax.set_xticks(range(len(names)), names, rotation=15)
        ax.set_ylabel("total tokens (K)")
        ax.set_title(f"{name(model)}, project x{scale}: resume tasks")
        ax.legend(frameon=False)
    fig.tight_layout()
    made.append(save(fig, outdir / "resume_tasks.png", plt))

    if any("multiday" in summary[m][max(summary[m])] for m in models):
        fig, axes = plt.subplots(1, len(models), figsize=(5.5 * len(models), 3.6), squeeze=False)
        for ax, model in zip(axes[0], models):
            scale = max(summary[model])
            days = summary[model][scale].get("multiday", {})
            boot = bootstrap_tokens(summary[model][scale]) or 0.0
            for cond in COND_LABEL:
                total = boot if cond == "context" else 0.0
                ys = [total / 1000]
                for t in days:
                    total += mean_sd(days[t][cond]["tokens"])[0] if cond in days[t] else 0.0
                    ys.append(total / 1000)
                ax.plot(range(len(ys)), ys, marker="o", color=COLORS[cond], label=COND_LABEL[cond])
            ax.set_xticks(range(len(days) + 1), ["first STATE"] + list(days))
            ax.set_ylabel("cumulative tokens (K)")
            ax.set_title(f"{name(model)}, project x{scale}: four days, first STATE included")
            ax.legend(frameon=False)
        fig.tight_layout()
        made.append(save(fig, outdir / "multiday_cumulative.png", plt))
    return made


def save(fig, path: Path, plt) -> Path:
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def update_readme(readme: Path, body: str) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        text = head + block + rest.split(END, 1)[1]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("records", type=Path, nargs="+")
    ap.add_argument("--prices", default="1,0.1,1.25,5",
                    help="fallback weights for uncached input, cache read, cache write, output, "
                         "used when a run's model variant has no list price")
    ap.add_argument("--price-table", type=Path, default=HERE / "prices.json")
    ap.add_argument("--figures", type=Path, default=HERE / "results" / "figures")
    ap.add_argument("--summary", type=Path, default=HERE / "results" / "summary.md")
    ap.add_argument("--readme", type=Path, help="also replace the benchmark block in this file")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args()

    prices = tuple(float(x) for x in args.prices.split(","))
    records = load(args.records)
    if not records:
        print("no finished records with usage", file=sys.stderr)
        return 1
    summary = summarize(records, prices, load_prices(args.price_table))
    body = tables(summary)
    if not args.no_figures:
        base = (args.readme or args.summary).resolve().parent
        imgs = [f"![{p.stem}]({Path(os.path.relpath(p.resolve(), base)).as_posix()})"
                for p in figures(summary, args.figures)]
        body = "\n\n".join(imgs) + "\n\n" + body
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(body + "\n", encoding="utf-8")
    if args.readme:
        update_readme(args.readme, body)
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
