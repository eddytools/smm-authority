import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Group, type ImportResult, type Insights, type Metrics, type PlanSlot, type Stage, type Venture } from "../api";

type Dim = "stage" | "post_type" | "platform" | "pillar";
const DIMS: { key: Dim; title: string }[] = [
  { key: "stage", title: "Funnel stage" },
  { key: "post_type", title: "Post type" },
  { key: "platform", title: "Platform" },
  { key: "pillar", title: "Pillar" },
];
const FIELDS: { key: keyof Metrics; label: string }[] = [
  { key: "impressions", label: "Impressions" },
  { key: "reactions", label: "Reactions" },
  { key: "comments", label: "Comments" },
  { key: "shares", label: "Shares" },
  { key: "saves", label: "Saves" },
  { key: "clicks", label: "Link clicks" },
  { key: "follows", label: "New follows" },
  { key: "leads", label: "Leads" },
];
const EMPTY: Metrics = { impressions: 0, reactions: 0, comments: 0, shares: 0, saves: 0, clicks: 0, follows: 0, leads: 0 };
const pct = (x: number | null | undefined, d = 1) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
const num = (x: number) => x.toLocaleString();
const date = (iso: string) => new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
const STAGES: Stage[] = ["tofu", "mofu", "bofu"];

export default function VentureInsights() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [days, setDays] = useState(90);
  const [data, setData] = useState<Insights | null>(null);
  const [published, setPublished] = useState<PlanSlot[]>([]);
  const [dim, setDim] = useState<Dim>("stage");
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [imported, setImported] = useState<ImportResult | null>(null);

  const load = useCallback(async () => {
    const [report, slots] = await Promise.all([api.getInsights(vid, days), api.listPlan(vid)]);
    setData(report);
    const since = Date.now() - days * 86_400_000;
    setPublished(
      slots
        .filter((s) => ["published", "analysed"].includes(s.status) && new Date(s.scheduled_at).getTime() >= since)
        .sort((a, b) => Number(a.has_metrics) - Number(b.has_metrics) || b.scheduled_at.localeCompare(a.scheduled_at)),
    );
  }, [vid, days]);

  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
  }, [vid]);
  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError("");
    try {
      const result = await api.importMetrics(vid, await file.text());
      setImported(result);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function downloadTemplate() {
    const waiting = published.filter((s) => !s.has_metrics);
    const csv = ["slot_id," + FIELDS.map((f) => f.key).join(","), ...waiting.map((s) => `${s.id},${FIELDS.map(() => "").join(",")}`)].join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "results-template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const rows = data?.breakdowns[dim] ?? [];
  const maxRate = useMemo(() => Math.max(0.0001, ...rows.map((r) => r.engagement_rate ?? 0)), [rows]);
  const t = data?.totals;
  const totalPlanned = data ? STAGES.reduce((n, s) => n + data.mix[s].planned, 0) : 0;
  const totalPublished = data ? STAGES.reduce((n, s) => n + data.mix[s].published, 0) : 0;

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Performance</h2>
        <span className="spacer" />
        <select aria-label="Time range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={180}>Last 180 days</option>
        </select>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {data === null && !error && <p className="muted">Loading…</p>}

      {data && t && (
        <>
          {data.note && <p className="notice" role="note">{data.note}</p>}
          {t.published === 0 && (
            <section className="card empty">
              <p>Nothing published in this period yet. Mark planned posts as Published in the planner, then enter their results here.</p>
              <Link to={`/ventures/${vid}/plan`} className="btn">Open the planner</Link>
            </section>
          )}

          <div className="tiles" aria-label="Summary">
            <Tile v={num(t.published)} l="Posts published" />
            <Tile v={`${t.measured} / ${t.published}`} l="With results" />
            <Tile v={num(t.impressions)} l="Impressions" />
            <Tile v={pct(t.engagement_rate)} l="Engagement rate" />
            <Tile v={pct(t.ctr)} l="Link click rate" />
            <Tile v={num(t.leads)} l="Leads" />
          </div>

          <div className="two">
            <section className="card worked">
              <h3>What worked</h3>
              {data.worked.length === 0 && <p className="muted small">Nothing stands out yet. This fills in once a few posts of each kind have results.</p>}
              {data.worked.map((f) => <p key={f.message} className="finding">{f.message}</p>)}
            </section>
            <section className="card didnt">
              <h3>What didn't</h3>
              {data.didnt.length === 0 && <p className="muted small">Nothing is clearly underperforming yet.</p>}
              {data.didnt.map((f) => <p key={f.message} className="finding">{f.message}</p>)}
            </section>
          </div>
          {data.recommendations.length > 0 && (
            <section className="card">
              <h3>Do next</h3>
              <ul>{data.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
              <p className="muted small">These are rules applied to your numbers, not AI opinions. The planner doesn't change by itself: adjust your funnel mix when you generate the next plan.</p>
            </section>
          )}

          <section className="card">
            <div className="week-nav">
              <h3 style={{ margin: 0 }}>Engagement rate by</h3>
              <div className="tabs" role="tablist">
                {DIMS.map((d) => (
                  <button key={d.key} role="tab" aria-selected={dim === d.key} className={dim === d.key ? "active" : ""} onClick={() => setDim(d.key)}>{d.title}</button>
                ))}
              </div>
            </div>
            {rows.length === 0 && <p className="muted">No results to compare yet.</p>}
            {rows.map((r) => <BarRow key={r.key} g={r} max={maxRate} />)}
            {rows.length > 0 && <p className="muted small">Engagement = reactions + comments + shares + saves, divided by impressions. Groups with fewer than 2 posts are shown but never called a win or a loss.</p>}
          </section>

          <div className="two">
            <section className="card">
              <h3>Best posts</h3>
              {data.top.length === 0 && <p className="muted small">Needs posts with impressions.</p>}
              {data.top.map((p) => <PostLine key={p.slot_id} p={p} />)}
            </section>
            <section className="card">
              <h3>Weakest posts</h3>
              {data.bottom.length === 0 && <p className="muted small">Shown once at least 4 posts have results.</p>}
              {data.bottom.map((p) => <PostLine key={p.slot_id} p={p} />)}
            </section>
          </div>

          <section className="card">
            <h3>Funnel balance and consistency</h3>
            <p className="small muted">
              {data.adherence.rate == null ? "No posts were due in this period." : `You published ${data.adherence.published} of ${data.adherence.due} planned posts (${pct(data.adherence.rate, 0)})${data.adherence.skipped ? `, ${data.adherence.skipped} skipped on purpose` : ""}.`}
            </p>
            {([["Planned", "planned", totalPlanned], ["Published", "published", totalPublished]] as const).map(([name, key, total]) => (
              <div key={key} className="bar-row" style={{ gridTemplateColumns: "90px 1fr 70px" }}>
                <span>{name}</span>
                <div className="mixbar" role="img" aria-label={`${name} mix: ${STAGES.map((s) => `${s} ${data.mix[s][key]}`).join(", ")}`}>
                  {STAGES.map((s) => total > 0 && <i key={s} className={s} style={{ width: `${(data.mix[s][key] / total) * 100}%` }} title={`${s.toUpperCase()} ${data.mix[s][key]}`} />)}
                </div>
                <span className="num small">{total} posts</span>
              </div>
            ))}
            <div className="legend" style={{ marginTop: ".4rem" }}>
              {STAGES.map((s) => <span key={s} className={`pill ${s}`}>{s.toUpperCase()}</span>)}
            </div>
          </section>
        </>
      )}

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Results</h3>
          <span className="spacer" />
          <button className="ghost" onClick={downloadTemplate} disabled={published.length === 0}>CSV template</button>
          <label className="btn ghost-label" style={{ cursor: "pointer" }}>
            Import CSV
            <input type="file" accept=".csv,text/csv" onChange={onFile} style={{ display: "none" }} aria-label="Import results CSV" />
          </label>
        </div>
        <p className="muted small">Enter the numbers from each platform's own analytics (until they can be pulled in automatically). Posts waiting for results come first.</p>
        {imported && (
          <div className="notice" role="status">
            Imported {imported.imported} row{imported.imported === 1 ? "" : "s"}.
            {imported.errors.length > 0 && (
              <ul>{imported.errors.slice(0, 8).map((e) => <li key={e.row}>Row {e.row}: {e.message}</li>)}</ul>
            )}
          </div>
        )}
        {published.length === 0 && <p className="muted">No published posts in this period.</p>}
        {published.map((s) => (
          <div key={s.id} className="result-row">
            <div className="result-head">
              <span className={`pill ${s.stage}`}>{s.stage.toUpperCase()}</span>
              <span className="topic">{s.topic}</span>
              <span className="muted small">{s.platform} · {date(s.scheduled_at)}</span>
              <span className={`badge ${s.has_metrics ? "" : "admin"}`}>{s.has_metrics ? "Results in" : "Waiting"}</span>
              <button className="ghost" onClick={() => setOpenId(openId === s.id ? null : s.id)} aria-expanded={openId === s.id}>
                {openId === s.id ? "Close" : s.has_metrics ? "Edit" : "Enter results"}
              </button>
            </div>
            {openId === s.id && (
              <ResultsForm
                vid={vid}
                slotId={s.id}
                onSaved={async () => {
                  setOpenId(null);
                  setNotice("Results saved.");
                  await load();
                }}
                onError={setError}
              />
            )}
          </div>
        ))}
      </section>
    </>
  );
}

function Tile({ v, l }: { v: string; l: string }) {
  return (
    <div className="tile">
      <div className="v">{v}</div>
      <div className="l">{l}</div>
    </div>
  );
}

function BarRow({ g, max }: { g: Group; max: number }) {
  const cls = g.lift != null && g.posts >= 2 ? (g.lift >= 1.25 ? "over" : g.lift <= 0.75 ? "under" : "") : "";
  return (
    <div className="bar-row" title={`${g.posts} posts · ${num(g.impressions)} impressions · ${g.leads} leads · click rate ${pct(g.ctr)}`}>
      <span>{g.label} <span className="muted small">({g.posts})</span></span>
      <div className={`bar ${cls}`} role="img" aria-label={`${g.label}: ${pct(g.engagement_rate)} engagement`}>
        <i style={{ width: `${((g.engagement_rate ?? 0) / max) * 100}%` }} />
      </div>
      <span className="num">{pct(g.engagement_rate)}</span>
    </div>
  );
}

function PostLine({ p }: { p: { topic: string; platform: string; scheduled_at: string; engagement_rate: number; impressions: number; stage: Stage; leads: number } }) {
  return (
    <div className="finding">
      <span className={`pill ${p.stage}`}>{p.stage.toUpperCase()}</span> {p.topic}
      <div className="muted small">
        {p.platform} · {date(p.scheduled_at)} · {pct(p.engagement_rate)} engagement · {num(p.impressions)} impressions{p.leads ? ` · ${p.leads} lead${p.leads === 1 ? "" : "s"}` : ""}
      </div>
    </div>
  );
}

function ResultsForm({ vid, slotId, onSaved, onError }: { vid: number; slotId: number; onSaved: () => Promise<void>; onError: (m: string) => void }) {
  const [v, setV] = useState<Metrics | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.getMetrics(vid, slotId).then((m) => setV(m ?? EMPTY)).catch((e: Error) => onError(e.message));
  }, [vid, slotId, onError]);
  if (!v) return <p className="muted small">Loading…</p>;
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api.saveMetrics(vid, slotId, v);
          await onSaved();
        } catch (err) {
          onError((err as Error).message);
          setBusy(false);
        }
      }}
    >
      <div className="metric-form">
        {FIELDS.map((f) => (
          <label key={f.key}>
            {f.label}
            <input type="number" min={0} step={1} value={v[f.key]} aria-label={f.label} onChange={(e) => setV({ ...v, [f.key]: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} />
          </label>
        ))}
        <button disabled={busy}>{busy ? "Saving…" : "Save results"}</button>
      </div>
    </form>
  );
}
