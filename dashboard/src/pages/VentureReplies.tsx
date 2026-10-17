import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Opportunity, type Reply, type Venture } from "../api";

type Tab = "open" | "posted" | "dismissed";
const words = (s: string) => (s.trim() ? s.trim().split(/\s+/).length : 0);
const ago = (iso: string) => {
  const h = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  return h < 1 ? "just now" : h < 24 ? `${Math.floor(h)}h ago` : `${Math.floor(h / 24)}d ago`;
};
const tomorrow9 = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

export default function VentureReplies() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [opps, setOpps] = useState<Opportunity[]>([]);
  const [replies, setReplies] = useState<Reply[] | null>(null);
  const [tab, setTab] = useState<Tab>("open");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState({ platform: "reddit" as "reddit" | "linkedin" | "x", community: "", source_url: "", question_text: "", community_rules: "", instructions: "" });

  const loadReplies = useCallback(async () => setReplies(await api.listReplies(vid, tab)), [vid, tab]);
  const loadOpps = useCallback(async () => setOpps(await api.listOpportunities(vid)), [vid]);

  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
    loadOpps().catch(() => setOpps([]));
  }, [vid, loadOpps]);
  useEffect(() => {
    loadReplies().catch((e: Error) => setError(e.message));
  }, [loadReplies]);

  async function guarded(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(null);
  }

  const draftFor = (o: Opportunity) =>
    guarded(`opp-${o.id}`, async () => {
      await api.draftReply(vid, { platform: "reddit", feed_item_id: o.id });
      setTab("open");
      await Promise.all([loadReplies(), loadOpps()]);
    });

  async function submit(e: FormEvent) {
    e.preventDefault();
    await guarded("form", async () => {
      await api.draftReply(vid, {
        platform: form.platform,
        question_text: form.question_text,
        ...(form.source_url.trim() && { source_url: form.source_url.trim() }),
        ...(form.community.trim() && { community: form.community.trim() }),
        ...(form.community_rules.trim() && { community_rules: form.community_rules.trim() }),
        ...(form.instructions.trim() && { instructions: form.instructions.trim() }),
      });
      setForm({ ...form, question_text: "", source_url: "", instructions: "" });
      setTab("open");
      await Promise.all([loadReplies(), loadOpps()]);
    });
  }

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Quick replies</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <section className="card stop">
        <h3>You post these yourself</h3>
        <p className="small" style={{ margin: 0 }}>
          Nothing here is ever posted for you. Copy a reply, read it, and post it from your own account. Communities dislike marketing, so these drafts are written to <strong>help first</strong>:
          no pitch and no links by default, and the checks below flag anything that looks like promotion or a claim you would need to back up. If you do mention your business, say that you're connected to it.
        </p>
      </section>

      <section className="card">
        <h3>Questions worth answering</h3>
        <p className="muted small">From your trend feed: recent, lively questions close to your niche. Replying early is what makes an answer useful.</p>
        {opps.length === 0 && <p className="muted">No open questions right now. Refresh your trend feed, or paste a thread below.</p>}
        {opps.map((o) => (
          <div key={o.id} className="opp">
            <span className="t">
              <a href={o.url} target="_blank" rel="noopener noreferrer">{o.title}</a>
              <span className="muted small"> · {o.source_label} · {o.age_hours < 1 ? "just now" : `${Math.round(o.age_hours)}h ago`}{o.engagement > 0 ? ` · ${o.engagement} engagement` : ""}</span>
            </span>
            <button onClick={() => draftFor(o)} disabled={busy !== null}>{busy === `opp-${o.id}` ? "Drafting…" : "Draft a reply"}</button>
          </div>
        ))}
      </section>

      <section className="card">
        <h3>Reply to something else</h3>
        <form onSubmit={submit}>
          <div className="two-col">
            <label>
              Where
              <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value as typeof form.platform })} style={{ width: "100%" }}>
                <option value="reddit">Reddit comment</option>
                <option value="linkedin">LinkedIn comment</option>
                <option value="x">X reply</option>
              </select>
            </label>
            {form.platform === "reddit" && (
              <label>
                Subreddit <span className="muted small">(optional)</span>
                <input value={form.community} placeholder="startups" onChange={(e) => setForm({ ...form, community: e.target.value })} />
              </label>
            )}
          </div>
          <label>
            Link to the thread <span className="muted small">(optional; one draft per thread)</span>
            <input type="url" placeholder="https://" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
          </label>
          <label>
            The question or post you're replying to
            <textarea rows={4} required minLength={10} maxLength={6000} value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} placeholder="Paste the title and text of the thread" />
          </label>
          <details>
            <summary>Community rules (recommended)</summary>
            <label>
              Paste the rules from the community's sidebar. If they ban links or self-promotion, the checks get stricter and the draft will avoid both.
              <textarea rows={3} maxLength={3000} value={form.community_rules} onChange={(e) => setForm({ ...form, community_rules: e.target.value })} />
            </label>
          </details>
          <label>
            Anything the reply should do <span className="muted small">(optional)</span>
            <input maxLength={500} value={form.instructions} placeholder="e.g. keep it short, ask a clarifying question" onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
          </label>
          <button disabled={busy !== null}>{busy === "form" ? "Drafting…" : "Draft a reply"}</button>
        </form>
      </section>

      <section className="card">
        <div className="tabs" role="tablist">
          {(["open", "posted", "dismissed"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => { if (t !== tab) { setReplies(null); setTab(t); } }}>
              {t === "open" ? "Your replies" : t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
        {replies === null && <p className="muted">Loading…</p>}
        {replies?.length === 0 && <p className="muted">{tab === "open" ? "No drafts yet. Pick a question above." : `Nothing ${tab} yet.`}</p>}
        {replies?.map((r) => (
          <ReplyCard
            key={r.id}
            reply={r}
            vid={vid}
            onChanged={async () => { await Promise.all([loadReplies(), loadOpps()]); }}
            onError={setError}
          />
        ))}
      </section>
    </>
  );
}

function ReplyCard({ reply, vid, onChanged, onError }: { reply: Reply; vid: number; onChanged: () => Promise<void>; onError: (m: string) => void }) {
  const [text, setText] = useState(reply.reply_draft);
  const [current, setCurrent] = useState(reply);
  const serverText = useRef(reply.reply_draft);
  // When the list reloads, take the fresh server state, but never overwrite text the user is in the middle of editing.
  useEffect(() => {
    setCurrent(reply);
    setText((t) => (t === serverText.current ? reply.reply_draft : t));
    serverText.current = reply.reply_draft;
  }, [reply]);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [plan, setPlan] = useState({ open: false, platform: "linkedin", when: tomorrow9() });
  const dirty = text !== current.reply_draft;

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    onError("");
    try {
      await fn();
    } catch (e) {
      onError((e as Error).message);
    }
    setBusy(null);
  };
  const apply = (r: Reply) => {
    setCurrent(r);
    setText(r.reply_draft);
    serverText.current = r.reply_draft;
  };

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      window.prompt("Copy the reply:", text); // clipboard blocked: let them copy by hand
    }
  }

  return (
    <article className="reply-card" aria-label={`Reply to ${current.community ?? current.platform}`}>
      <div className="result-head">
        <span className="badge">{current.platform}</span>
        {current.community && <strong>r/{current.community}</strong>}
        <span className="muted small">{ago(current.created_at)}</span>
        <span className="spacer" />
        {current.source_url && <a href={current.source_url} target="_blank" rel="noopener noreferrer" className="small">Open the thread ↗</a>}
      </div>
      <details style={{ margin: ".4rem 0" }}>
        <summary className="small muted">The question</summary>
        <div className="q">{current.question_text}</div>
      </details>

      <textarea aria-label="Reply" value={text} onChange={(e) => setText(e.target.value)} disabled={current.status !== "open"} maxLength={6000} />
      <div className="draft-meta small muted">{words(text)} words · {text.length} characters</div>
      {current.warnings.length > 0 && !dirty && (
        <ul className="warn-list" aria-label="Checks">
          {current.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      {dirty && <p className="muted small">Save your edits to re-run the checks.</p>}
      {current.notes && <p className="notice" role="status">{current.notes}</p>}

      {current.status === "open" && (
        <>
          <div className="row">
            <button className={current.warnings.length && !dirty ? "ghost" : ""} onClick={copy}>
              {copied ? "Copied" : current.warnings.length && !dirty ? "Copy anyway" : "Copy reply"}
            </button>
            {dirty && <button className="ghost" disabled={busy !== null} onClick={() => act("save", async () => apply(await api.updateReply(vid, current.id, { reply_draft: text })))}>Save edits</button>}
            <button className="ghost" disabled={busy !== null || dirty} onClick={() => act("posted", async () => { await api.updateReply(vid, current.id, { status: "posted" }); await onChanged(); })} title="Mark it as posted once you have posted it yourself">I posted it</button>
            <button className="ghost" disabled={busy !== null} onClick={() => act("dismiss", async () => { await api.updateReply(vid, current.id, { status: "dismissed" }); await onChanged(); })}>Dismiss</button>
          </div>
          <div className="ai-draft" style={{ marginTop: ".6rem" }}>
            <input aria-label="Redraft instructions" placeholder="Redraft: e.g. shorter, friendlier, ask a question first" value={instructions} maxLength={500} onChange={(e) => setInstructions(e.target.value)} />
            <button className="ghost" disabled={busy !== null} onClick={() => { if (!dirty || window.confirm("Replace your edits with a new draft?")) void act("redraft", async () => apply(await api.redraftReply(vid, current.id, instructions.trim() || null))); }}>
              {busy === "redraft" ? "Drafting…" : "Redraft"}
            </button>
          </div>
        </>
      )}
      {current.status !== "open" && (
        <div className="row">
          <button className="ghost" onClick={() => act("restore", async () => { await api.updateReply(vid, current.id, { status: "open" }); await onChanged(); })}>Move back to your replies</button>
          <button className="ghost danger" onClick={() => { if (window.confirm("Delete this reply?")) void act("delete", async () => { await api.deleteReply(vid, current.id); await onChanged(); }); }}>Delete</button>
        </div>
      )}

      {current.post_idea && (
        <div className="idea">
          <h5>Post idea for your own channel: {current.post_idea_title}</h5>
          <p className="small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{current.post_idea}</p>
          {current.plan_slot_id ? (
            <p className="small"><Link to={`/ventures/${vid}/plan`}>Added to your plan →</Link></p>
          ) : plan.open ? (
            <div className="row" style={{ marginTop: ".5rem", alignItems: "end" }}>
              <label className="inline">
                Platform
                <select value={plan.platform} onChange={(e) => setPlan({ ...plan, platform: e.target.value })}>
                  {["linkedin", "x", "instagram", "youtube", "blog", "newsletter"].map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
              <label className="inline">
                When
                <input type="datetime-local" value={plan.when} onChange={(e) => setPlan({ ...plan, when: e.target.value })} aria-label="Plan date and time" />
              </label>
              <button disabled={busy !== null} onClick={() => act("plan", async () => { await api.replyToPlan(vid, current.id, { scheduled_at: new Date(plan.when).toISOString(), platform: plan.platform }); await onChanged(); })}>Add to plan</button>
              <button className="ghost" onClick={() => setPlan({ ...plan, open: false })}>Cancel</button>
            </div>
          ) : (
            <button className="ghost" style={{ marginTop: ".4rem" }} onClick={() => setPlan({ ...plan, open: true })}>Add this idea to my plan</button>
          )}
        </div>
      )}
    </article>
  );
}
