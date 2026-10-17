"""'What worked / what didn't': a deterministic report over published posts and their results.

Pure functions, no AI, no DB. Every number and sentence is derived from the data with thresholds written below,
so the report is free to run, reproducible, and honest about small samples."""

import math
from collections import defaultdict
from datetime import datetime

from app.framework import DEFAULT_MIX, LABEL, STAGE_GOAL, PostType, Stage

MIN_GROUP = 2  # a group needs this many measured posts before we draw any conclusion about it
WORKED_LIFT = 1.25  # engagement rate at least 25% above your average
DIDNT_LIFT = 0.75  # at least 25% below
SMALL_SAMPLE = 10
DIMENSIONS = ("platform", "pillar", "post_type", "stage")
DIMENSION_TITLE = {"platform": "Platform", "pillar": "Pillar", "post_type": "Post type", "stage": "Funnel stage"}
PLATFORM_NAME = {"linkedin": "LinkedIn", "x": "X", "reddit": "Reddit", "instagram": "Instagram", "youtube": "YouTube", "blog": "Blog", "newsletter": "Newsletter"}
PUBLISHED = {"published", "analysed"}
NO_PILLAR = "(no pillar)"


def label_for(dimension: str, key: str) -> str:
    if dimension == "platform":
        return PLATFORM_NAME.get(key, key)
    if dimension == "post_type":
        return LABEL[PostType(key)]
    if dimension == "stage":
        return f"{STAGE_GOAL[Stage(key)]} ({key.upper()})"
    return key


def _engagements(m: dict) -> int:
    return m["reactions"] + m["comments"] + m["shares"] + m["saves"]


def _ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def _round(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


def _aggregate(rows: list[dict]) -> dict:
    imp = sum(r["metrics"]["impressions"] for r in rows)
    eng = sum(_engagements(r["metrics"]) for r in rows)
    clicks = sum(r["metrics"]["clicks"] for r in rows)
    return {
        "posts": len(rows),
        "impressions": imp,
        "avg_impressions": _round(imp / len(rows), 1) if rows else 0,
        "engagements": eng,
        "engagement_rate": _round(_ratio(eng, imp)),
        "clicks": clicks,
        "ctr": _round(_ratio(clicks, imp)),
        "follows": sum(r["metrics"]["follows"] for r in rows),
        "leads": sum(r["metrics"]["leads"] for r in rows),
    }


MIN_MIX_POSTS = 12  # measured posts needed before we suggest changing the funnel mix
MAX_MIX_SHIFT = 10  # percentage points a stage may move in one suggestion
MIN_STAGE_SHARE = 10  # a stage you plan at all keeps at least this share
STAGES = [st.value for st in Stage]


def suggest_mix(measured: list[dict], current: dict[str, int]) -> dict:
    """A cautious funnel-mix suggestion from results. Each stage is scored by how its engagement rate (and, once there are
    at least 3 leads, leads per post) compares with your average; shares move toward the better stages by at most
    MAX_MIX_SHIFT points. Stages with fewer than MIN_GROUP measured posts are left alone. It's a nudge, not an optimiser."""
    base = {"current": dict(current), "suggested": dict(current), "changed": False, "reasons": []}
    if len(measured) < MIN_MIX_POSTS:
        return {**base, "ready": False, "reasons": [f"Needs at least {MIN_MIX_POSTS} posts with results before the planner can suggest a mix (you have {len(measured)})."]}
    total = _aggregate(measured)
    use_leads = total["leads"] >= 3
    per_stage = {st: [r for r in measured if r["stage"] == st] for st in STAGES}
    scores: dict[str, float] = {}
    judged: list[str] = []
    notes: dict[str, str] = {}
    for st, rows in per_stage.items():
        if len(rows) < MIN_GROUP or not total["engagement_rate"]:
            scores[st] = 1.0
            continue
        agg = _aggregate(rows)
        eng = (agg["engagement_rate"] or 0) / total["engagement_rate"]
        lead = ((agg["leads"] / len(rows)) / (total["leads"] / len(measured))) if use_leads else eng
        scores[st] = max(0.25, min(4.0, (eng + lead) / 2))
        judged.append(st)
        notes[st] = f"{eng:.1f}× engagement" + (f", {lead:.1f}× leads per post" if use_leads else "") + f" ({len(rows)} posts)"
    # Only stages with enough results trade share with each other; the rest keep exactly what they have.
    pool = sum(current[st] for st in judged)
    weights = {st: current[st] * math.sqrt(scores[st]) for st in judged}
    norm = sum(weights.values()) or 1
    target = {st: (weights[st] / norm * pool if st in weights else float(current[st])) for st in STAGES}
    lo = {st: (current[st] if st not in weights else 0 if current[st] == 0 else max(MIN_STAGE_SHARE, current[st] - MAX_MIX_SHIFT)) for st in STAGES}
    hi = {st: (current[st] if st not in weights else 0 if current[st] == 0 else min(100, current[st] + MAX_MIX_SHIFT)) for st in STAGES}
    out = {st: max(lo[st], min(hi[st], round(target[st]))) for st in STAGES}
    while sum(out.values()) != 100:
        diff = 100 - sum(out.values())
        room = {st: ((hi[st] - out[st]) if diff > 0 else (out[st] - lo[st])) for st in STAGES}
        st = max(STAGES, key=lambda k: (room[k], target[k] if diff > 0 else -target[k]))
        if room[st] <= 0:
            break
        out[st] += 1 if diff > 0 else -1
    reasons = []
    for st in STAGES:
        if out[st] != current[st]:
            verb = "up" if out[st] > current[st] else "down"
            reasons.append(f"{STAGE_GOAL[Stage(st)]} ({st.upper()}) {verb} from {current[st]}% to {out[st]}%: {notes.get(st, 'no clear signal')}.")
    thin = [st.upper() for st in STAGES if len(per_stage[st]) < MIN_GROUP and current[st] > 0]
    if thin:
        reasons.append(f"Not enough results to judge {', '.join(thin)}, so {'it was' if len(thin) == 1 else 'they were'} left out of the comparison.")
    if not any(out[st] != current[st] for st in STAGES):
        reasons.insert(0, "Your results don't point to a clear change: keep your current mix.")
    return {"ready": True, "current": dict(current), "suggested": out, "changed": out != dict(current), "reasons": reasons}


def build_report(rows: list[dict], now: datetime, since: datetime, days: int, current_mix: dict[str, int] | None = None) -> dict:
    """rows: one dict per slot in the window with keys slot_id, scheduled_at, platform, pillar, post_type, stage, topic,
    status and metrics (a dict of counts, or None when no results were entered)."""
    published = [r for r in rows if r["status"] in PUBLISHED]
    measured = [r for r in published if r["metrics"]]
    totals = _aggregate(measured)
    overall = totals["engagement_rate"]

    breakdowns: dict[str, list[dict]] = {}
    groups: dict[str, dict[str, list[dict]]] = {d: defaultdict(list) for d in DIMENSIONS}
    for r in measured:
        for d in DIMENSIONS:
            groups[d][(r.get("pillar") or NO_PILLAR) if d == "pillar" else r[d]].append(r)
    for d in DIMENSIONS:
        items = []
        for key, grp in groups[d].items():
            agg = _aggregate(grp)
            lift = _ratio(agg["engagement_rate"] or 0, overall or 0) if agg["engagement_rate"] is not None else None
            items.append({"key": key, "label": label_for(d, key), **agg, "lift": _round(lift, 2)})
        breakdowns[d] = sorted(items, key=lambda i: (-(i["engagement_rate"] or 0), -i["posts"], i["label"]))

    worked, didnt = [], []
    if overall:
        for d in DIMENSIONS:
            for item in breakdowns[d]:
                if item["posts"] < MIN_GROUP or item["lift"] is None or len(breakdowns[d]) < 2:
                    continue
                weight = abs(math.log(max(item["lift"], 0.01))) * math.sqrt(item["posts"])
                base = {"dimension": d, "dimension_title": DIMENSION_TITLE[d], "key": item["key"], "label": item["label"], "posts": item["posts"], "lift": item["lift"], "weight": weight}
                if item["lift"] >= WORKED_LIFT:
                    worked.append({**base, "message": f"{item['label']} posts earn {item['lift']:.1f}× your average engagement rate ({item['engagement_rate']:.1%} vs {overall:.1%}, {item['posts']} posts)."})
                elif item["lift"] <= DIDNT_LIFT:
                    didnt.append({**base, "message": f"{item['label']} posts are underperforming: {item['engagement_rate']:.1%} engagement vs your {overall:.1%} average ({item['posts']} posts)."})
    worked = sorted(worked, key=lambda i: -i["weight"])[:6]
    didnt = sorted(didnt, key=lambda i: -i["weight"])[:6]
    for i in worked + didnt:
        i.pop("weight")

    if totals["leads"] >= 3:
        stage_leads = sorted(((r["stage"], sum(x["metrics"]["leads"] for x in measured if x["stage"] == r["stage"])) for r in measured), key=lambda t: -t[1])
        top_stage, top_leads = stage_leads[0]
        n = sum(1 for x in measured if x["stage"] == top_stage)
        worked.append({
            "dimension": "leads", "dimension_title": "Leads", "key": top_stage, "label": label_for("stage", top_stage), "posts": n, "lift": None,
            "message": f"{label_for('stage', top_stage)} posts brought {top_leads} of your {totals['leads']} leads ({top_leads / totals['leads']:.0%}) from {n} posts.",
        })

    recommendations = [f"Plan more {i['label']} posts." for i in worked if i["dimension"] in ("post_type", "pillar", "platform")][:3]
    recommendations += [f"Rework or cut back {i['label']} posts: try a stronger opening line or a different angle." for i in didnt if i["dimension"] in ("post_type", "pillar", "platform")][:2]

    ranked = sorted((r for r in measured if r["metrics"]["impressions"] > 0), key=lambda r: -_engagements(r["metrics"]) / r["metrics"]["impressions"])

    def post_view(r: dict) -> dict:
        m = r["metrics"]
        return {"slot_id": r["slot_id"], "topic": r["topic"], "platform": r["platform"], "post_type": r["post_type"], "stage": r["stage"], "scheduled_at": r["scheduled_at"],
                "impressions": m["impressions"], "engagement_rate": _round(_engagements(m) / m["impressions"]), "leads": m["leads"]}

    top = [post_view(r) for r in ranked[:3]]
    bottom = [post_view(r) for r in ranked[-3:][::-1]] if len(ranked) >= 4 else []

    due = [r for r in rows if r["scheduled_at"] <= now and r["status"] != "archived"]
    skipped = sum(r["status"] == "skipped" for r in due)
    done = sum(r["status"] in PUBLISHED for r in due)
    expected = len(due) - skipped
    mix = {st.value: {"planned": sum(1 for r in due if r["status"] != "skipped" and r["stage"] == st.value), "published": sum(1 for r in due if r["status"] in PUBLISHED and r["stage"] == st.value)} for st in Stage}

    return {
        "range_days": days,
        "since": since,
        "totals": {**totals, "published": len(published), "measured": len(measured)},
        "breakdowns": breakdowns,
        "worked": worked,
        "didnt": didnt,
        "recommendations": recommendations,
        "top": top,
        "bottom": bottom,
        "adherence": {"due": expected, "published": done, "skipped": skipped, "rate": _round(_ratio(done, expected), 3)},
        "mix": mix,
        "mix_suggestion": suggest_mix(measured, current_mix or DEFAULT_MIX),
        "waiting": [{"slot_id": r["slot_id"], "topic": r["topic"], "platform": r["platform"], "scheduled_at": r["scheduled_at"]} for r in published if not r["metrics"]],
        "note": (f"Based on only {len(measured)} measured post{'s' if len(measured) != 1 else ''}: treat these as hints, not conclusions." if len(measured) < SMALL_SAMPLE else None),
    }
