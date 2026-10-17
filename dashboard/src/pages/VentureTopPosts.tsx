import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TopPosts, type Venture } from "../api";

export default function VentureTopPosts() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [data, setData] = useState<TopPosts | null>(null);
  const [days, setDays] = useState(60);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
  }, [vid]);
  useEffect(() => {
    setData(null);
    api.getTopPosts(vid, days).then(setData).catch((e: Error) => setError(e.message));
  }, [vid, days]);

  const works = data?.patterns.filter((p) => p.verdict === "works") ?? [];
  const flat = data?.patterns.filter((p) => p.verdict === "flat") ?? [];
  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Why top posts win</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <section className="card">
        <div className="week-nav">
          <p className="muted small" style={{ margin: 0 }}>
            Looks at posts from the subreddits, influencers and groups you track. A post counts as a high performer when it beats its own source's typical post by 1.5× or more. Rule-based, not AI.
          </p>
          <span className="spacer" />
          <label className="small">
            Last{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Window">
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
        </div>
        {data && (
          <p className="small">
            {data.posts} posts analysed, {data.high_performers} high performers.
          </p>
        )}
        {data?.note && <p className="muted">{data.note}</p>}
      </section>

      {works.length > 0 && (
        <section className="card">
          <h3>What the winners share</h3>
          <ul className="plain">
            {works.map((p) => (
              <li key={p.tag}>
                <strong>{p.label}</strong> <span className="badge trend-rising">{p.lift}× the average</span>
                <span className="muted small"> {p.posts} posts · {Math.round(p.high_share * 100)}% were high performers</span>
                <div className="small">{p.advice}</div>
                <div className="small muted">
                  e.g. <a href={p.example.url} target="_blank" rel="noreferrer noopener">{p.example.title}</a> ({p.example.community}, {p.example.engagement})
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {flat.length > 0 && (
        <section className="card">
          <h3>What falls flat</h3>
          <ul className="plain">
            {flat.map((p) => (
              <li key={p.tag}>
                <strong>{p.label}</strong> <span className="badge trend-cooling">{p.lift}× the average</span>
                <span className="muted small"> {p.posts} posts</span>
                <div className="small">{p.advice}</div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && data.top.length > 0 && (
        <section className="card">
          <h3>The top posts</h3>
          <ul className="plain">
            {data.top.map((t) => (
              <li key={t.url}>
                <a href={t.url} target="_blank" rel="noreferrer noopener">{t.title}</a>
                <div className="small muted">{t.community} · {t.engagement} engagement · {t.relative}× its source's typical post</div>
                <div className="small">{t.tags.map((x) => <span key={x} className="badge">{x}</span>)}</div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="muted small">
        These are correlations in a small sample, not proof of cause: a post may do well because of its topic, timing or author as much as its shape. Use them as things to test in your own posts, then check the results on the Performance page.
      </p>
    </>
  );
}
