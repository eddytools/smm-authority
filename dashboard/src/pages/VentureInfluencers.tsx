import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Digest, type Influencer, type InfluencerPlatform, type Venture } from "../api";

const PLATFORMS: InfluencerPlatform[] = ["linkedin", "x", "reddit", "youtube", "blog", "newsletter", "other"];
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
const blank = { name: "", platform: "linkedin" as InfluencerPlatform, profile_url: "", feed_url: "", notes: "" };

export default function VentureInfluencers() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [list, setList] = useState<Influencer[] | null>(null);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [form, setForm] = useState(blank);
  const [pasting, setPasting] = useState<number | null>(null);
  const [post, setPost] = useState({ url: "", text: "", engagement: "" });
  const [takePlatform, setTakePlatform] = useState<"linkedin" | "x">("linkedin");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [l, d] = await Promise.all([api.listInfluencers(vid), api.getDigest(vid)]);
    setList(l);
    setDigest(d);
  }, [vid]);
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

  const add = (e: FormEvent) => {
    e.preventDefault();
    return run(async () => {
      await api.addInfluencer(vid, {
        name: form.name,
        platform: form.platform,
        ...(form.profile_url.trim() && { profile_url: form.profile_url.trim() }),
        ...(form.feed_url.trim() && { feed_url: form.feed_url.trim() }),
        ...(form.notes.trim() && { notes: form.notes.trim() }),
      });
      setForm(blank);
    });
  };

  const submitPost = (e: FormEvent, id: number) => {
    e.preventDefault();
    return run(async () => {
      await api.addInfluencerPost(vid, id, { url: post.url, text: post.text, engagement: Number(post.engagement) || 0 });
      setPost({ url: "", text: "", engagement: "" });
      setPasting(null);
      return "Post added. It now appears in your trend feed too.";
    });
  };

  const planTake = (term: string) =>
    run(async () => {
      await api.createSlot(vid, { scheduled_at: tomorrow9(), platform: takePlatform, post_type: "educational", topic: `Our take on ${term}` });
      return `Added “Our take on ${term}” to your planner as an idea for tomorrow at 9:00. Open the planner to change it.`;
    });

  const count = list?.length ?? 0;
  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Influencer watch</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <section className="card">
        <h3>What they're talking about</h3>
        {digest && digest.topics.length === 0 && (
          <p className="muted">{digest.note ?? "No topic yet comes up in posts from at least two of the people you follow. Add more voices or paste in their recent posts."}</p>
        )}
        {digest && digest.topics.length > 0 && (
          <>
            <p className="muted small">Words that show up in posts from at least two different people in the last {digest.days} days, counted across {digest.posts} posts. A rule-based count, not AI.</p>
            <label className="small">
              Plan my take on:{" "}
              <select value={takePlatform} onChange={(e) => setTakePlatform(e.target.value as "linkedin" | "x")}>
                <option value="linkedin">LinkedIn</option>
                <option value="x">X</option>
              </select>
            </label>
            <ul className="plain">
              {digest.topics.map((t) => (
                <li key={t.term} className="topic">
                  <strong>{t.term}</strong>
                  <span className="muted small"> {t.voices} voices · {t.posts} posts{t.engagement > 0 ? ` · ${t.engagement} engagement` : ""}</span>
                  {t.in_niche && <span className="badge">your niche</span>}
                  {t.covered ? <span className="badge admin">you've covered it</span> : <span className="badge">not in your plan</span>}
                  <div className="small muted">
                    {t.influencers.join(", ")} — e.g. <a href={t.example.url} target="_blank" rel="noreferrer noopener">{t.example.title}</a>
                  </div>
                  {!t.covered && <button className="ghost" disabled={busy} onClick={() => planTake(t.term)}>Plan my take</button>}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h3>People you follow {count > 0 && <span className="muted small">({count})</span>}</h3>
        <p className="muted small">
          Blogs, newsletters, YouTube channels and Reddit users can be followed automatically through their feed link. LinkedIn and X can't be read automatically,
          so for those you paste in the posts you notice (with the numbers shown on the post).
        </p>
        {list?.length === 0 && <p className="muted">Nobody yet. Add the 3–10 people your ideal customers already listen to.</p>}
        {list?.map((i) => (
          <div key={i.id} className="influencer">
            <div className="meta">
              <strong>{i.profile_url ? <a href={i.profile_url} target="_blank" rel="noreferrer noopener">{i.name}</a> : i.name}</strong>
              <span className="badge">{i.platform}</span>
              {!i.enabled && <span className="badge">paused</span>}
              <span className="muted small">
                {i.posts_30d} post{i.posts_30d === 1 ? "" : "s"} in 30 days
                {i.avg_engagement !== null && ` · avg ${i.avg_engagement} engagement`}
                {i.last_post_at && ` · last ${ago(i.last_post_at)}`}
              </span>
              <span className="spacer" />
              <button className="ghost" onClick={() => setPasting(pasting === i.id ? null : i.id)}>Paste a post</button>
              <button className="ghost" disabled={busy} onClick={() => run(async () => void (await api.updateInfluencer(vid, i.id, { enabled: !i.enabled })))}>{i.enabled ? "Pause" : "Resume"}</button>
              <button
                className="ghost danger"
                disabled={busy}
                onClick={() => window.confirm(`Stop following ${i.name}? Their collected posts are removed from your feed too, including saved ones.`) && run(async () => void (await api.deleteInfluencer(vid, i.id)))}
              >
                Remove
              </button>
            </div>
            {i.notes && <p className="small muted" style={{ margin: ".2rem 0" }}>{i.notes}</p>}
            {i.feed_url && <p className="small muted" style={{ margin: ".2rem 0" }}>Feed: {i.feed_url}{i.last_status === "error" && <span className="error"> · last fetch failed: {i.last_error}</span>}</p>}
            {pasting === i.id && (
              <form className="stack" onSubmit={(e) => submitPost(e, i.id)}>
                <label>
                  Link to the post
                  <input required value={post.url} onChange={(e) => setPost({ ...post, url: e.target.value })} placeholder="https://www.linkedin.com/posts/…" />
                </label>
                <label>
                  The post's text
                  <textarea required rows={4} maxLength={5000} value={post.text} onChange={(e) => setPost({ ...post, text: e.target.value })} />
                </label>
                <label>
                  Reactions + comments shown (optional)
                  <input type="number" min={0} value={post.engagement} onChange={(e) => setPost({ ...post, engagement: e.target.value })} />
                </label>
                <button disabled={busy}>Add post</button>
              </form>
            )}
          </div>
        ))}

        <form className="stack" onSubmit={add}>
          <h4>Follow someone</h4>
          <div className="row">
            <label>
              Name
              <input required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              Where they post
              <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value as InfluencerPlatform })}>
                {PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
          </div>
          <label>
            Profile link (optional)
            <input value={form.profile_url} onChange={(e) => setForm({ ...form, profile_url: e.target.value })} placeholder="https://" />
          </label>
          <label>
            Feed link, if they have one (optional)
            <input value={form.feed_url} onChange={(e) => setForm({ ...form, feed_url: e.target.value })} placeholder="https://their-blog.com/feed.xml" />
          </label>
          <label>
            Why you follow them (optional)
            <input maxLength={300} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          <button disabled={busy || !form.name.trim()}>Follow</button>
        </form>
      </section>

      {digest && digest.voices.length > 0 && (
        <section className="card">
          <h3>Their best recent posts</h3>
          <ul className="plain">
            {digest.voices.map((v) => (
              <li key={v.influencer_id}>
                <strong>{v.influencer}</strong> <span className="muted small">{v.posts} post{v.posts === 1 ? "" : "s"} · avg {v.avg_engagement}</span>
                <div className="small"><a href={v.top_post.url} target="_blank" rel="noreferrer noopener">{v.top_post.title}</a> <span className="muted">({v.top_post.engagement} engagement)</span></div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
