import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Community, type CommunityPlatform, type Heat, type Trend, type Venture } from "../api";

const PLATFORMS: CommunityPlatform[] = ["linkedin", "facebook", "slack", "discord", "reddit", "other"];
const TREND_TEXT: Record<Trend, string> = { rising: "▲ rising", steady: "● steady", cooling: "▼ cooling", new: "✦ new this period", unknown: "" };
const ago = (iso: string) => {
  const h = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  return h < 1 ? "just now" : h < 24 ? `${Math.floor(h)}h ago` : `${Math.floor(h / 24)}d ago`;
};
const tomorrow9 = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return d.toISOString();
};
const blank = { name: "", platform: "linkedin" as CommunityPlatform, url: "", notes: "" };

export default function VentureCommunities() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [groups, setGroups] = useState<Community[] | null>(null);
  const [heat, setHeat] = useState<Heat | null>(null);
  const [days, setDays] = useState(14);
  const [form, setForm] = useState(blank);
  const [pasting, setPasting] = useState<number | null>(null);
  const [post, setPost] = useState({ url: "", text: "", likes: "", comments: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [g, h] = await Promise.all([api.listCommunities(vid), api.getHeat(vid, days)]);
    setGroups(g);
    setHeat(h);
  }, [vid, days]);
  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
  }, [vid]);
  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

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

  const add = (e: FormEvent) => {
    e.preventDefault();
    return run(async () => {
      await api.addCommunity(vid, {
        name: form.name,
        platform: form.platform,
        ...(form.url.trim() && { url: form.url.trim() }),
        ...(form.notes.trim() && { notes: form.notes.trim() }),
      });
      setForm(blank);
    });
  };

  const submitPost = (e: FormEvent, id: number) => {
    e.preventDefault();
    return run(async () => {
      await api.addCommunityPost(vid, id, { url: post.url, text: post.text, likes: Number(post.likes) || 0, comments: Number(post.comments) || 0 });
      setPost({ url: "", text: "", likes: "", comments: "" });
      setPasting(null);
      return "Post added. It now appears in your trend feed too.";
    });
  };

  const planTake = (term: string) =>
    run(async () => {
      await api.createSlot(vid, { scheduled_at: tomorrow9(), platform: "linkedin", post_type: "educational", topic: `Our take on ${term}` });
      return `Added “Our take on ${term}” to your planner as an idea for tomorrow at 9:00 on LinkedIn. Open the planner to change it.`;
    });

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Community heat</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <section className="card">
        <div className="week-nav">
          <h3 style={{ margin: 0 }}>What's hot</h3>
          <span className="spacer" />
          <label className="small">
            Last{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Window">
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
            </select>
          </label>
        </div>
        {heat?.note && <p className="muted">{heat.note}</p>}
        {heat && heat.topics.length === 0 && !heat.note && <p className="muted">No topic shows up in at least two posts yet.</p>}
        {heat && heat.topics.length > 0 && (
          <>
            <p className="muted small">
              {heat.posts} posts from {heat.communities.map((c) => c.community).join(", ")}. A topic's heat adds up how much each post beat its own community's typical post, so a small group and a huge subreddit
              are compared fairly. A rule-based count, not AI.{!heat.has_baseline && " Trends need an earlier period to compare with, so none are shown yet."}
            </p>
            <ul className="plain">
              {heat.topics.map((t) => (
                <li key={t.term} className="topic">
                  <strong>{t.term}</strong>
                  {t.trend !== "unknown" && <span className={`badge trend-${t.trend}`}>{TREND_TEXT[t.trend]}</span>}
                  <span className="muted small"> {t.posts} posts · {t.engagement} likes & comments · {t.avg_relative}× a typical post</span>
                  {t.in_niche && <span className="badge">your niche</span>}
                  {t.covered ? <span className="badge admin">you've covered it</span> : <span className="badge">not in your plan</span>}
                  <div className="small muted">
                    {t.communities.join(", ")} — e.g. <a href={t.example.url} target="_blank" rel="noreferrer noopener">{t.example.title}</a> ({t.example.engagement})
                  </div>
                  {!t.covered && <button className="ghost" disabled={busy} onClick={() => planTake(t.term)}>Plan my take</button>}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {heat && heat.hot_posts.length > 0 && (
        <section className="card">
          <h3>Posts that beat their community's usual</h3>
          <ul className="plain">
            {heat.hot_posts.map((p) => (
              <li key={p.url}>
                <a href={p.url} target="_blank" rel="noreferrer noopener">{p.title}</a>
                <div className="small muted">{p.community} · {p.engagement} likes & comments · {p.relative}× that community's typical post</div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h3>Groups you track</h3>
        <p className="muted small">
          Subreddits are read automatically: add one as a Reddit source on the <Link to={`/ventures/${vid}/feed`}>trend feed</Link>. Groups on LinkedIn, Facebook, Slack or Discord can't be read automatically, so
          add the group here and paste in the posts you notice, with their likes and comments.
        </p>
        {groups?.length === 0 && <p className="muted">No groups yet.</p>}
        {groups?.map((g) => (
          <div key={g.id} className="influencer">
            <div className="meta">
              <strong>{g.url ? <a href={g.url} target="_blank" rel="noreferrer noopener">{g.name}</a> : g.name}</strong>
              <span className="badge">{g.platform}</span>
              {!g.enabled && <span className="badge">paused</span>}
              <span className="muted small">
                {g.posts_30d} post{g.posts_30d === 1 ? "" : "s"} in 30 days
                {g.median_engagement !== null && ` · typical ${g.median_engagement} likes & comments`}
                {g.last_post_at && ` · last ${ago(g.last_post_at)}`}
              </span>
              <span className="spacer" />
              <button className="ghost" onClick={() => setPasting(pasting === g.id ? null : g.id)}>Paste a post</button>
              <button className="ghost" disabled={busy} onClick={() => run(async () => void (await api.updateCommunity(vid, g.id, { enabled: !g.enabled })))}>{g.enabled ? "Pause" : "Resume"}</button>
              <button
                className="ghost danger"
                disabled={busy}
                onClick={() => window.confirm(`Stop tracking ${g.name}? The posts you pasted for it are removed from your feed too, including saved ones.`) && run(async () => void (await api.deleteCommunity(vid, g.id)))}
              >
                Remove
              </button>
            </div>
            {g.notes && <p className="small muted" style={{ margin: ".2rem 0" }}>{g.notes}</p>}
            {pasting === g.id && (
              <form className="stack" onSubmit={(e) => submitPost(e, g.id)}>
                <label>
                  Link to the post
                  <input required value={post.url} onChange={(e) => setPost({ ...post, url: e.target.value })} placeholder="https://" />
                </label>
                <label>
                  The post's text
                  <textarea required rows={4} maxLength={5000} value={post.text} onChange={(e) => setPost({ ...post, text: e.target.value })} />
                </label>
                <div className="row">
                  <label>
                    Likes
                    <input type="number" min={0} value={post.likes} onChange={(e) => setPost({ ...post, likes: e.target.value })} />
                  </label>
                  <label>
                    Comments
                    <input type="number" min={0} value={post.comments} onChange={(e) => setPost({ ...post, comments: e.target.value })} />
                  </label>
                </div>
                <button disabled={busy}>Add post</button>
              </form>
            )}
          </div>
        ))}

        <form className="stack" onSubmit={add}>
          <h4>Track a group</h4>
          <div className="row">
            <label>
              Name
              <input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              Where it lives
              <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value as CommunityPlatform })}>
                {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
          </div>
          <label>
            Link (optional)
            <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://" />
          </label>
          <label>
            Notes (optional)
            <input maxLength={300} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          <button disabled={busy || !form.name.trim()}>Track</button>
        </form>
      </section>
    </>
  );
}
