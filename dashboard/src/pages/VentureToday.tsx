import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Health, type Today, type TodaySlot, type Venture } from "../api";
import { Avatar, SourceIcon } from "../components/Icons";

const ago = (iso: string | null) => {
  if (!iso) return "never";
  const m = (Date.now() - new Date(iso).getTime()) / 60_000;
  return m < 1 ? "just now" : m < 60 ? `${Math.floor(m)} min ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`;
};
const HEALTH_TEXT: Record<Health, string> = { ok: "Fetched", error: "Failed", stale: "Not fetched in 24h", never: "Never fetched", paused: "Paused", manual: "Pasted by you" };
const TREND: Record<string, string> = { rising: "▲", cooling: "▼", new: "✦", steady: "●", unknown: "" };
const STATUS_TEXT: Record<string, string> = { idea: "Idea", drafted: "Drafted", in_review: "In review", approved: "Approved", scheduled: "Scheduled", published: "Published", analysed: "Analysed", skipped: "Skipped" };
const dayLabel = (iso: string, today: boolean) => (today ? "Today" : new Date(iso + "T12:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric" }));
const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

function Progress({ pct, tone }: { pct: number | null; tone?: "good" | "bad" }) {
  return (
    <div className={`progress ${tone ?? ""}`} role="progressbar" aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${pct ?? 0}%` }} />
    </div>
  );
}

export default function VentureToday() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [data, setData] = useState<Today | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => setData(await api.getToday(vid)), [vid]);
  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
    load().catch((e: Error) => setError(e.message));
  }, [vid, load]);

  async function run(fn: () => Promise<string | void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const msg = await fn();
      if (msg) setNotice(msg);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const fetchNow = () =>
    run(async () => {
      const r = await api.refreshFeed(vid);
      const failed = r.sources.filter((s) => s.status === "error").length;
      return `Fetched ${r.new_items} new item${r.new_items === 1 ? "" : "s"} from ${r.sources.length} source${r.sources.length === 1 ? "" : "s"}${failed ? `, ${failed} failed` : ""}.`;
    });

  const planTake = (term: string) =>
    run(async () => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      await api.createSlot(vid, { scheduled_at: d.toISOString(), platform: "linkedin", post_type: "educational", topic: `Our take on ${term}` });
      return `Added “Our take on ${term}” to your calendar for tomorrow at 9:00 on LinkedIn.`;
    });

  const base = `/ventures/${vid}`;
  const linkFor = (l: string | null) => (l === "setup" ? `${base}/setup` : l ? `${base}/${l}` : base);
  const f = data?.fetch;
  const max = Math.max(1, ...(f?.by_day.map((d) => d.items) ?? [1]));
  const cov = f?.coverage;
  const tone = cov?.pct == null ? undefined : cov.pct === 100 ? "good" : cov.pct < 50 ? "bad" : undefined;

  return (
    <>
      <p>
        <Link to="/">← Ventures</Link>
      </p>
      <div className="page-head">
        <h2>{venture?.name ?? "Today"}</h2>
        <span className="muted">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</span>
        <span className="spacer" />
        {f?.last_fetched_at && <span className="muted small">Last fetched {ago(f.last_fetched_at)}</span>}
        <button onClick={fetchNow} disabled={busy}>{busy ? "Working…" : "Fetch now"}</button>
        <Link to={`${base}/setup`} className="btn">Setup</Link>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {!data && !error && <p className="muted">Loading…</p>}

      {data && f && (
        <>
          <div className="tiles" aria-label="Fetch statistics">
            <div className="tile">
              <div className="label">Fetched, last 24h</div>
              <div className="big">{f.items_24h}</div>
              <div className="spark" aria-label="Items fetched per day, last 7 days">
                {f.by_day.map((d) => <i key={d.date} style={{ height: `${Math.max(6, (d.items / max) * 100)}%` }} title={`${d.date}: ${d.items}`} />)}
              </div>
              <div className="muted small">{f.items_7d} in 7 days</div>
            </div>
            <div className="tile">
              <div className="label">Sources healthy</div>
              <div className="big">{cov && cov.sources ? `${cov.ok}/${cov.sources}` : "0"}</div>
              <Progress pct={cov?.pct ?? null} tone={tone} />
              <div className="muted small">
                {cov && cov.sources ? `${cov.error ? `${cov.error} failing` : "none failing"}${cov.stale ? `, ${cov.stale} stale` : ""}` : "No sources yet"}
              </div>
            </div>
            <div className="tile">
              <div className="label">To review</div>
              <div className="big">{f.unreviewed}</div>
              <div className="muted small"><Link to={`${base}/feed`}>Open the trend feed</Link></div>
            </div>
            <div className="tile">
              <div className="label">This week's posts</div>
              <div className="big">{data.calendar.week.planned ? `${data.calendar.week.published}/${data.calendar.week.planned}` : "0"}</div>
              <Progress pct={data.calendar.week.pct} tone={data.calendar.week.pct === 100 ? "good" : undefined} />
              <div className="muted small">published of planned</div>
            </div>
            {data.calendar.late.length > 0 && (
              <div className="tile warn">
                <div className="label">Missed their date</div>
                <div className="big">{data.calendar.late.length}</div>
                <div className="muted small"><Link to={`${base}/plan`}>Reschedule or publish</Link></div>
              </div>
            )}
          </div>

          <div className="cols">
            <section className="card">
              <h3>What's trending</h3>
              {data.trending.items.length === 0 && <p className="muted">Nothing fetched in the last 3 days. Add sources on the <Link to={`${base}/feed`}>trend feed</Link>, then press Fetch now.</p>}
              {data.trending.items.map((i) => (
                <div className="row-item" key={i.id}>
                  <SourceIcon type={i.icon} size={26} title={i.source_label} />
                  <div className="body">
                    <a className="title" href={i.url} target="_blank" rel="noreferrer noopener">{i.title}</a>
                    <span className="muted small">
                      {i.influencer ? `★ ${i.influencer}` : i.source_label} · {ago(i.published_at)}
                      {i.engagement > 0 && ` · ${i.engagement} engagement`}
                    </span>
                    {i.why && <div className="small">{i.why}</div>}
                  </div>
                  <span className="pillscore" title={i.ai_scored ? "AI relevance to your niche" : "Match score (keywords, freshness, engagement)"}>{i.score}</span>
                </div>
              ))}
              {data.trending.topics.length > 0 && (
                <>
                  <h4>Hot in your communities</h4>
                  <div className="chips">
                    {data.trending.topics.map((t) => (
                      <span key={t.term} className={`chip2 ${t.trend === "rising" ? "up" : t.trend === "cooling" ? "down" : ""}`} title={`${t.posts} posts in ${t.communities.join(", ")}`}>
                        {TREND[t.trend]} {t.term}
                      </span>
                    ))}
                  </div>
                  <Link to={`${base}/communities`} className="small">All community heat →</Link>
                </>
              )}
            </section>

            <section className="card">
              <h3>What influencers are writing</h3>
              {data.influencers.total === 0 && <p className="muted">You're not following anyone yet. <Link to={`${base}/influencers`}>Add 3 to 10 voices in your niche</Link>.</p>}
              {data.influencers.people.map((p) => (
                <div className="row-item" key={p.id}>
                  <Avatar name={p.name} url={p.avatar_url} platform={p.platform} size={42} />
                  <div className="body">
                    <strong>{p.profile_url ? <a href={p.profile_url} target="_blank" rel="noreferrer noopener">{p.name}</a> : p.name}</strong>{" "}
                    <span className="muted small">{p.posts_7d} post{p.posts_7d === 1 ? "" : "s"} this week</span>
                    {p.latest ? (
                      <div className="small">
                        <a href={p.latest.url} target="_blank" rel="noreferrer noopener">{p.latest.title}</a>{" "}
                        <span className="muted">{ago(p.latest.published_at)}{p.latest.engagement > 0 && ` · ${p.latest.engagement}`}</span>
                      </div>
                    ) : (
                      <div className="small muted">No posts yet. Paste one in, or add their feed.</div>
                    )}
                  </div>
                </div>
              ))}
              {data.influencers.topics.length > 0 && (
                <>
                  <h4>They're all talking about</h4>
                  <div className="chips">
                    {data.influencers.topics.map((t) => (
                      <span key={t.term} className="chip2" title={`${t.influencers.join(", ")}`}>{t.term} <span className="muted small">{t.voices} voices</span></span>
                    ))}
                  </div>
                </>
              )}
              {data.influencers.total > 0 && <Link to={`${base}/influencers`} className="small">Manage influencers →</Link>}
            </section>
          </div>

          <section className="card">
            <h3>Suggested for you</h3>
            {data.suggestions.length === 0 && <p className="muted">You're caught up. Nothing needs attention right now.</p>}
            {data.suggestions.map((s, i) => (
              <div className="sugg" key={i}>
                <div className="body">
                  <div className="kind">{{ topic_gap: "Topic to cover", draft: "Needs a draft", reply: "Question to answer", saved: "Saved item", setup: "Get started" }[s.kind]}</div>
                  <strong>{s.title}</strong>
                  <div className="muted small">{s.detail}</div>
                </div>
                {s.kind === "topic_gap" && s.term ? (
                  <button className="ghost" disabled={busy} onClick={() => planTake(s.term!)}>Plan my take</button>
                ) : (
                  <Link className="btn" to={linkFor(s.link)}>Open</Link>
                )}
              </div>
            ))}
          </section>

          <section className="card">
            <div className="page-head" style={{ marginBottom: ".5rem" }}>
              <h3 style={{ margin: 0 }}>My calendar, next 7 days</h3>
              <span className="spacer" />
              <Link to={`${base}/plan`} className="small">Open the planner →</Link>
            </div>
            {data.calendar.total_upcoming === 0 && <p className="muted small">Nothing planned for the next 7 days. <Link to={`${base}/plan`}>Generate a plan</Link>.</p>}
            <div className="cal">
              {data.calendar.days.map((d) => (
                <div key={d.date} className={`cal-day ${d.is_today ? "today" : ""}`}>
                  <h5>{dayLabel(d.date, d.is_today)}</h5>
                  {d.slots.map((s: TodaySlot) => (
                    <Link key={s.id} to={`${base}/plan`} className={`cal-slot ${s.stage}`} title={s.topic}>
                      <SourceIcon type={s.platform} size={18} />
                      <span>
                        {s.topic.length > 38 ? s.topic.slice(0, 36) + "…" : s.topic}
                        <div className="st">{time(s.scheduled_at)} · {STATUS_TEXT[s.status] ?? s.status}{s.will_auto_publish ? " · auto" : ""}</div>
                      </span>
                    </Link>
                  ))}
                </div>
              ))}
            </div>
            {data.calendar.late.length > 0 && (
              <p className="error small">
                Missed their date: {data.calendar.late.map((s) => s.topic).slice(0, 3).join(", ")}. <Link to={`${base}/plan`}>Open the planner</Link>.
              </p>
            )}
          </section>

          <section className="card">
            <h3>Fetched details</h3>
            {f.sources.length === 0 ? (
              <p className="muted">No sources yet. <Link to={`${base}/feed`}>Add RSS feeds, subreddits or a news search</Link>.</p>
            ) : (
              <table className="fetch">
                <thead>
                  <tr><th>Source</th><th>Status</th><th>Last update</th><th>New, 24h</th><th>7 days</th></tr>
                </thead>
                <tbody>
                  {f.sources.map((s) => (
                    <tr key={s.id}>
                      <td><span style={{ display: "inline-flex", alignItems: "center", gap: ".5rem" }}><SourceIcon type={s.icon} size={22} />{s.kind === "influencer" ? "★ " : ""}{s.label}</span></td>
                      <td><span className={`dot ${s.health}`} />{HEALTH_TEXT[s.health]}{s.error && <div className="error small" style={{ margin: 0 }}>{s.error}</div>}</td>
                      <td className="muted">{ago(s.last_fetched_at)}</td>
                      <td>{s.new_24h}</td>
                      <td>{s.items_7d}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <div className="tools">
            <Link to={`${base}/feed`}>Trend feed</Link>
            <Link to={`${base}/plan`}>Content planner</Link>
            <Link to={`${base}/influencers`}>Influencer watch</Link>
            <Link to={`${base}/communities`}>Community heat</Link>
            <Link to={`${base}/top-posts`}>Why top posts win</Link>
            <Link to={`${base}/replies`}>Quick replies</Link>
            <Link to={`${base}/insights`}>Performance</Link>
            <Link to={`${base}/publishing`}>Publishing</Link>
          </div>
        </>
      )}
    </>
  );
}
