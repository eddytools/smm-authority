import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type FeedItem, type ItemStatus, type Source, type SourceType, type Venture } from "../api";

type Tab = "new" | "saved" | "dismissed";

const PLACEHOLDER: Record<SourceType, string> = {
  rss: "https://example.com/feed.xml",
  reddit: "subreddit, e.g. startups",
  google_news: "search query, e.g. founder-led growth",
  manual: "",
};
const TYPE_LABEL: Record<SourceType, string> = { rss: "RSS", reddit: "Reddit", google_news: "Google News", manual: "Pasted" };

function ago(iso: string): string {
  const hours = Math.max(0, (Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function VentureFeed() {
  const vid = Number(useParams().id);
  const navigate = useNavigate();
  const [venture, setVenture] = useState<Venture | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [tab, setTab] = useState<Tab>("new");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState<"refresh" | "score" | null>(null);
  const [form, setForm] = useState<{ type: SourceType; target: string }>({ type: "rss", target: "" });

  const loadItems = useCallback(async () => setItems(await api.listFeed(vid, tab)), [vid, tab]);

  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
    api.listSources(vid).then(setSources).catch((e: Error) => setError(e.message));
  }, [vid]);

  useEffect(() => {
    loadItems().catch((e: Error) => setError(e.message));
  }, [loadItems]);

  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  async function addSource(e: FormEvent) {
    e.preventDefault();
    const submitted = form;
    await run(async () => {
      const s = await api.addSource(vid, submitted);
      setSources((cur) => [...cur, s]);
      // Clear only if the user hasn't started typing something else while the request was in flight.
      setForm((cur) => (cur.type === submitted.type && cur.target === submitted.target ? { ...cur, target: "" } : cur));
    });
  }

  async function refresh() {
    setBusy("refresh");
    setNotice("");
    await run(async () => {
      const r = await api.refreshFeed(vid);
      const failed = r.sources.filter((s) => s.status === "error").length;
      setNotice(`${r.new_items} new item${r.new_items === 1 ? "" : "s"}${failed ? `, ${failed} source${failed === 1 ? "" : "s"} failed (see below)` : ""}.`);
      setSources(await api.listSources(vid));
      await loadItems();
    });
    setBusy(null);
  }

  async function score() {
    setBusy("score");
    setNotice("");
    await run(async () => {
      const r = await api.scoreFeed(vid);
      setNotice(r.scored ? `AI scored ${r.scored} item${r.scored === 1 ? "" : "s"}.` : "Nothing new to score.");
      await loadItems();
    });
    setBusy(null);
  }

  async function replyTo(item: FeedItem) {
    await run(async () => {
      try {
        await api.draftReply(vid, { platform: "reddit", feed_item_id: item.id });
        navigate(`/ventures/${vid}/replies`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) navigate(`/ventures/${vid}/replies`); // already drafted: take them to it
        else throw e;
      }
    });
  }

  async function mark(item: FeedItem, status: ItemStatus) {
    await run(async () => {
      await api.setItemStatus(vid, item.id, status);
      setItems((cur) => cur?.filter((i) => i.id !== item.id) ?? null);
    });
  }

  const enabledCount = sources.filter((s) => s.enabled).length;

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Trend feed</h2>
        <span className="spacer" />
        <button className="ghost" onClick={score} disabled={busy !== null}>
          {busy === "score" ? "Scoring…" : "Score with AI"}
        </button>
        <button onClick={refresh} disabled={busy !== null || enabledCount === 0}>
          {busy === "refresh" ? "Fetching…" : "Refresh now"}
        </button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <section className="card">
        <h3>Sources</h3>
        <p className="muted small">
          Fetched automatically on a schedule and whenever you press Refresh. Items are ranked by how well they match your setup, freshness and
          engagement; AI scoring is optional and only runs when you ask.
        </p>
        {sources.length === 0 && <p className="muted">No sources yet. Add an RSS feed, a subreddit or a Google News query.</p>}
        {sources.map((s) => (
          <div key={s.id} className="source-row">
            <span className="badge">{TYPE_LABEL[s.type]}</span>
            <span className="target" style={{ opacity: s.enabled ? 1 : 0.5 }}>{s.target}</span>
            <span className="small">
              {s.last_status === "ok" && <span className="status-ok">OK · {ago(s.last_fetched_at!)}</span>}
              {s.last_status === "error" && <span className="status-error" title={s.last_error ?? ""}>Failed: {s.last_error}</span>}
              {s.last_status === null && <span className="muted">Not fetched yet</span>}
            </span>
            <button className="ghost" onClick={() => run(async () => { const u = await api.updateSource(vid, s.id, { enabled: !s.enabled }); setSources((c) => c.map((x) => (x.id === s.id ? u : x))); })}>
              {s.enabled ? "Pause" : "Resume"}
            </button>
            <button className="ghost danger" onClick={() => run(async () => { await api.deleteSource(vid, s.id); setSources((c) => c.filter((x) => x.id !== s.id)); await loadItems(); })}>
              Remove
            </button>
          </div>
        ))}
        <form onSubmit={addSource} className="source-form">
          <select aria-label="Source type" value={form.type} onChange={(e) => setForm({ type: e.target.value as SourceType, target: "" })}>
            {(Object.keys(TYPE_LABEL) as SourceType[]).map((t) => (
              <option key={t} value={t}>{TYPE_LABEL[t]}</option>
            ))}
          </select>
          <input aria-label="Source target" placeholder={PLACEHOLDER[form.type]} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} required />
          <button>Add source</button>
        </form>
      </section>

      <section className="card">
        <div className="tabs" role="tablist">
          {(["new", "saved", "dismissed"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => { if (t !== tab) { setItems(null); setTab(t); } }}>
              {t === "new" ? "Feed" : t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        {items === null && <p className="muted">Loading…</p>}
        {items?.length === 0 && (
          <p className="muted">
            {tab === "new" ? (sources.length ? "Nothing left to review. Press Refresh now for more." : "Add a source to start.") : `Nothing ${tab} yet.`}
          </p>
        )}
        {items?.map((item) => (
          <article key={item.id} className="feed-item">
            <h4>
              <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
            </h4>
            <div className="meta">
              {item.relevance !== null ? (
                <span className="score" title="AI relevance to your niche">{item.relevance}</span>
              ) : (
                <span className="score rule" title="Match score (setup keywords, freshness, engagement). Use Score with AI for a sharper ranking.">{Math.round(item.rule_score)}</span>
              )}
              <span>{item.influencer_name ? `★ ${item.influencer_name}` : item.source_label}</span>
              <span>{ago(item.published_at)}</span>
              {item.engagement > 0 && <span>{item.engagement} engagement</span>}
              <span className="spacer" />
              {(item.source_type === "reddit" || item.title.includes("?")) && tab === "new" && (
                <button className="ghost" onClick={() => replyTo(item)} title="Draft a helpful reply you can post yourself">Draft a reply</button>
              )}
              {tab !== "saved" && <button className="ghost" onClick={() => mark(item, "saved")}>Save</button>}
              {tab !== "dismissed" ? (
                <button className="ghost" onClick={() => mark(item, "dismissed")}>Dismiss</button>
              ) : (
                <button className="ghost" onClick={() => mark(item, "new")}>Restore</button>
              )}
            </div>
            {item.why_it_matters && <p className="why">{item.why_it_matters}</p>}
            {!item.why_it_matters && item.summary && <p className="why muted clamp">{item.summary}</p>}
          </article>
        ))}
      </section>
    </>
  );
}
