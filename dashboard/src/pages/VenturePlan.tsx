import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Framework, type PlanSlot, type SlotStatus, type Stage, type Venture } from "../api";

const CHAR_LIMIT: Record<string, number> = { x: 280, linkedin: 3000, instagram: 2200, youtube: 5000 };

const READ_ONLY: SlotStatus[] = ["published", "analysed", "archived"];
const STAGES: Stage[] = ["tofu", "mofu", "bofu"];
const STATUS_FLOW: SlotStatus[] = ["idea", "drafted", "in_review", "approved", "scheduled", "published", "analysed"];
const label = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const pad = (n: number) => String(n).padStart(2, "0");
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  return `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const mondayOf = (d: Date) => {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
};
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const nextMonday = () => dayKey(addDays(mondayOf(new Date()), 7));
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export default function VenturePlan() {
  const vid = Number(useParams().id);
  const [venture, setVenture] = useState<Venture | null>(null);
  const [fw, setFw] = useState<Framework | null>(null);
  const [slots, setSlots] = useState<PlanSlot[] | null>(null);
  const [week, setWeek] = useState(() => mondayOf(new Date()));
  const [view, setView] = useState<"week" | "list">("week");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [overDay, setOverDay] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [gen, setGen] = useState({ start: nextMonday(), period: "month" as "week" | "month", tofu: 50, mofu: 30, bofu: 20 });

  const landed = useRef(false);
  const load = useCallback(async () => {
    const list = await api.listPlan(vid);
    setSlots(list);
    // First load only: open on the week of the next planned post, not on an empty current week.
    if (!landed.current && list.length) {
      landed.current = true;
      const now = Date.now();
      const thisWeek = dayKey(mondayOf(new Date()));
      if (!list.some((s) => dayKey(mondayOf(new Date(s.scheduled_at))) === thisWeek)) {
        const upcoming = list.find((s) => new Date(s.scheduled_at).getTime() >= now) ?? list[0];
        setWeek(mondayOf(new Date(upcoming.scheduled_at)));
      }
    }
  }, [vid]);
  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
    api.getFramework().then(setFw).catch((e: Error) => setError(e.message));
    load().catch((e: Error) => setError(e.message));
  }, [vid, load]);

  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const mixTotal = gen.tofu + gen.mofu + gen.bofu;
  const types = useMemo(() => (fw ? Object.fromEntries(fw.stages.flatMap((s) => s.post_types.map((t) => [t.key, { ...t, stage: s.key }]))) : {}), [fw]);
  const selected = slots?.find((s) => s.id === selectedId) ?? null;

  async function generate(replace = false) {
    setBusy(true);
    setNotice("");
    try {
      const r = await api.generatePlan(vid, {
        start_date: gen.start,
        period: gen.period,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        mix: { tofu: gen.tofu, mofu: gen.mofu, bofu: gen.bofu },
        replace,
      });
      setNotice(`Planned ${r.created} posts (${r.by_stage.tofu} growth, ${r.by_stage.mofu} trust, ${r.by_stage.bofu} selling)${r.kept ? `. Kept ${r.kept} you had already edited` : ""}.`);
      setWeek(mondayOf(new Date(gen.start + "T00:00")));
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && window.confirm(`${e.message}\n\nReplace the posts you haven't edited or locked?`)) {
        await generate(true);
        return;
      }
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function patch(slot: PlanSlot, data: Parameters<typeof api.updateSlot>[2]) {
    await run(async () => {
      const updated = await api.updateSlot(vid, slot.id, data);
      setSlots((cur) => cur?.map((s) => (s.id === updated.id ? updated : s)).sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at)) ?? null);
    });
  }

  function onDrop(e: DragEvent, day: Date) {
    e.preventDefault();
    setOverDay(null);
    const slot = slots?.find((s) => s.id === Number(e.dataTransfer.getData("text/plain")));
    if (!slot || READ_ONLY.includes(slot.status)) return;
    const old = new Date(slot.scheduled_at);
    if (dayKey(old) === dayKey(day)) return;
    const moved = new Date(day.getFullYear(), day.getMonth(), day.getDate(), old.getHours(), old.getMinutes());
    void patch(slot, { scheduled_at: moved.toISOString() });
  }

  const days = Array.from({ length: 7 }, (_, i) => addDays(week, i));
  const byDay = useMemo(() => {
    const m = new Map<string, PlanSlot[]>();
    slots?.forEach((s) => {
      const k = dayKey(new Date(s.scheduled_at));
      m.set(k, [...(m.get(k) ?? []), s]);
    });
    return m;
  }, [slots]);
  const weekSlots = days.flatMap((d) => byDay.get(dayKey(d)) ?? []);
  const count = (list: PlanSlot[], st: Stage) => list.filter((s) => s.stage === st).length;

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Content planner</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <section className="card">
        <h3>Generate a plan</h3>
        <p className="muted small">
          Built from your Authority setup: your platforms and weekly cadence, your pillars, saved items from the trend feed, and a growth → trust → sell rhythm across the month.
          Nothing is posted automatically.
        </p>
        <div className="gen-form">
          <label>
            Start date
            <input type="date" value={gen.start} onChange={(e) => setGen({ ...gen, start: e.target.value })} />
          </label>
          <label>
            Period
            <select value={gen.period} onChange={(e) => setGen({ ...gen, period: e.target.value as "week" | "month" })}>
              <option value="month">Month (4 weeks)</option>
              <option value="week">Week</option>
            </select>
          </label>
          {STAGES.map((st) => (
            <label key={st}>
              {st.toUpperCase()} % <span className="muted small">{fw?.stages.find((s) => s.key === st)?.goal}</span>
              <input type="number" min={0} max={100} aria-label={`${st} percent`} value={gen[st]} onChange={(e) => setGen({ ...gen, [st]: Number(e.target.value) || 0 })} />
            </label>
          ))}
          <button onClick={() => generate(false)} disabled={busy || mixTotal !== 100 || !gen.start}>
            {busy ? "Planning…" : "Generate plan"}
          </button>
        </div>
        {mixTotal !== 100 && <p className="error">Funnel mix adds up to {mixTotal}%, it needs to be 100%.</p>}
      </section>

      <section className="card">
        <div className="week-nav">
          <div className="tabs" role="tablist">
            {(["week", "list"] as const).map((v) => (
              <button key={v} role="tab" aria-selected={view === v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                {v === "week" ? "Week" : "List"}
              </button>
            ))}
          </div>
          {view === "week" && (
            <>
              <button className="ghost" aria-label="Previous week" onClick={() => setWeek(addDays(week, -7))}>←</button>
              <strong>
                {days[0].toLocaleDateString([], { month: "short", day: "numeric" })} – {days[6].toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
              </strong>
              <button className="ghost" aria-label="Next week" onClick={() => setWeek(addDays(week, 7))}>→</button>
              <button className="ghost" onClick={() => setWeek(mondayOf(new Date()))}>Today</button>
            </>
          )}
          <span className="spacer" />
          <div className="legend" aria-label="Funnel stages">
            {STAGES.map((st) => (
              <span key={st} className={`pill ${st}`}>
                {st.toUpperCase()} · {count(view === "week" ? weekSlots : slots ?? [], st)}
              </span>
            ))}
          </div>
        </div>

        {slots === null && <p className="muted">Loading…</p>}
        {slots?.length === 0 && <p className="muted">Nothing planned yet. Generate a plan above (choose your platforms in the Authority setup first).</p>}

        {view === "week" && slots && slots.length > 0 && (
          <div className="week-grid">
            {days.map((d) => {
              const k = dayKey(d);
              return (
                <div
                  key={k}
                  className={`day ${overDay === k ? "over" : ""} ${k === dayKey(new Date()) ? "today" : ""}`}
                  data-day={k}
                  onDragOver={(e) => { e.preventDefault(); setOverDay(k); }}
                  onDragLeave={() => setOverDay((cur) => (cur === k ? null : cur))}
                  onDrop={(e) => onDrop(e, d)}
                >
                  <h5>{d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</h5>
                  {(byDay.get(k) ?? []).map((s) => (
                    <button
                      key={s.id}
                      className={`chip ${s.stage} ${selectedId === s.id ? "sel" : ""} ${s.status === "skipped" ? "dim" : ""}`}
                      draggable={!READ_ONLY.includes(s.status)}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(s.id))}
                      onClick={() => setSelectedId(s.id)}
                      aria-label={`${s.platform} ${label(s.post_type)} on ${k}`}
                    >
                      <span className="t">{timeOf(s.scheduled_at)} · {s.platform}</span>
                      <span>{types[s.post_type]?.label ?? s.post_type}{s.locked ? " 🔒" : ""}{s.reactive ? " ⚡" : ""}</span>
                      <span className="m">{label(s.status)}</span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {view === "list" && slots && slots.length > 0 && (
          <table className="list">
            <thead>
              <tr><th>When</th><th>Platform</th><th>Type</th><th>Topic</th><th>Status</th></tr>
            </thead>
            <tbody>
              {slots.map((s) => (
                <tr key={s.id} onClick={() => setSelectedId(s.id)} style={{ cursor: "pointer" }}>
                  <td>{new Date(s.scheduled_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
                  <td>{s.platform}</td>
                  <td><span className={`pill ${s.stage}`}>{types[s.post_type]?.label ?? s.post_type}</span></td>
                  <td>{s.topic}</td>
                  <td>{label(s.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {view === "week" && <p className="muted small">Drag a post to another day to reschedule it. ⚡ marks a slot reserved for a timely post. 🔒 slots are kept when you regenerate.</p>}
      </section>

      {selected && fw && (
        <Editor
          key={selected.id}
          slot={selected}
          vid={vid}
          fw={fw}
          onClose={() => setSelectedId(null)}
          onPatch={(data) => patch(selected, data)}
          onDelete={() =>
            run(async () => {
              if (!window.confirm("Delete this planned post?")) return;
              await api.deleteSlot(vid, selected.id);
              setSlots((cur) => cur?.filter((s) => s.id !== selected.id) ?? null);
              setSelectedId(null);
            })
          }
        />
      )}
    </>
  );
}

function Editor({ slot, vid, fw, onClose, onPatch, onDelete }: { slot: PlanSlot; vid: number; fw: Framework; onClose: () => void; onPatch: (d: Parameters<typeof api.updateSlot>[2]) => Promise<void>; onDelete: () => void }) {
  const [f, setF] = useState({ topic: slot.topic, pillar: slot.pillar ?? "", cta: slot.cta ?? "", draft: slot.draft ?? "", when: toLocalInput(slot.scheduled_at) });
  const readOnly = READ_ONLY.includes(slot.status);
  const [ai, setAi] = useState<{ instructions: string; busy: boolean; hooks: string[]; notes: string; error: string }>({ instructions: "", busy: false, hooks: [], notes: "", error: "" });
  const typeInfo = fw.stages.flatMap((s) => s.post_types.map((t) => ({ ...t, stage: s.key }))).find((t) => t.key === slot.post_type);
  const next = fw.transitions[slot.status] ?? [];

  const dirty =
    f.topic !== slot.topic || f.pillar !== (slot.pillar ?? "") || f.cta !== (slot.cta ?? "") || f.draft !== (slot.draft ?? "") || f.when !== toLocalInput(slot.scheduled_at);

  async function draftWithAi() {
    if (f.draft.trim() && !window.confirm("Replace the current draft with a new AI draft?")) return;
    setAi((a) => ({ ...a, busy: true, error: "", notes: "", hooks: [] }));
    try {
      const r = await api.draftSlot(vid, slot.id, ai.instructions.trim() || null);
      setF((cur) => ({ ...cur, draft: r.draft }));
      setAi((a) => ({ ...a, busy: false, hooks: r.hooks, notes: r.notes }));
    } catch (e) {
      setAi((a) => ({ ...a, busy: false, error: (e as Error).message }));
    }
  }

  // swap the first line for an alternative hook
  const useHook = (hook: string) => setF((cur) => ({ ...cur, draft: [hook, ...cur.draft.split("\n").slice(1)].join("\n") }));

  const limit = CHAR_LIMIT[slot.platform];
  const len = f.draft.length;
  const save = (extra: Parameters<typeof api.updateSlot>[2] = {}) =>
    onPatch({
      ...(readOnly ? {} : { topic: f.topic.trim(), pillar: f.pillar.trim() || null, cta: f.cta.trim() || null, draft: f.draft, scheduled_at: new Date(f.when).toISOString() }),
      ...extra,
    });

  return (
    <section className="card editor" aria-label="Edit planned post">
      <div className="page-head">
        <h3>
          <span className={`pill ${slot.stage}`}>{slot.stage.toUpperCase()}</span> {typeInfo?.label} on {slot.platform}
        </h3>
        <span className="spacer" />
        <button className="ghost" onClick={onClose}>Close</button>
      </div>
      <p className="muted small">{typeInfo?.guidance}</p>

      <div className="pipeline" aria-label="Status">
        {STATUS_FLOW.map((s) => (
          <span key={s} className={`step ${slot.status === s ? "now" : ""}`}>{label(s)}</span>
        ))}
        {(slot.status === "skipped" || slot.status === "archived") && <span className="step now">{label(slot.status)}</span>}
      </div>

      {readOnly && <p className="muted small">This post has gone out, so its content is locked. You can still move its status forward.</p>}
      <label>
        Topic
        <input value={f.topic} onChange={(e) => setF({ ...f, topic: e.target.value })} disabled={readOnly} maxLength={300} />
      </label>
      <div className="grid2">
        <label>
          When
          <input type="datetime-local" value={f.when} onChange={(e) => setF({ ...f, when: e.target.value })} disabled={readOnly} />
        </label>
        <label>
          Pillar
          <input value={f.pillar} onChange={(e) => setF({ ...f, pillar: e.target.value })} disabled={readOnly} />
        </label>
        <label>
          Call to action
          <input value={f.cta} onChange={(e) => setF({ ...f, cta: e.target.value })} disabled={readOnly} />
        </label>
      </div>
      <label>
        Draft <span className="muted small">(required before the post can move past “Idea”)</span>
        <textarea value={f.draft} onChange={(e) => setF({ ...f, draft: e.target.value })} disabled={readOnly} maxLength={10000} aria-label="Draft" />
      </label>
      <div className="draft-meta small">
        <span className={limit && len > limit ? "status-error" : "muted"} aria-label="Character count">
          {len}{limit ? ` / ${limit}` : ""} characters
        </span>
      </div>
      {slot.warnings.length > 0 && (
        <ul className="warnings" aria-label="Draft warnings">
          {slot.warnings.map((w) => <li key={w}>{w}</li>)}
        </ul>
      )}
      {!readOnly && (
        <div className="ai-draft">
          <input
            aria-label="Instructions for the AI"
            placeholder="Optional: e.g. make it shorter, more contrarian, open with a question"
            value={ai.instructions}
            maxLength={500}
            onChange={(e) => setAi({ ...ai, instructions: e.target.value })}
          />
          <button className="ghost" onClick={draftWithAi} disabled={ai.busy}>
            {ai.busy ? "Drafting…" : f.draft.trim() ? "Redraft with AI" : "Draft with AI"}
          </button>
        </div>
      )}
      {ai.error && <p className="error" role="alert">{ai.error}</p>}
      {ai.notes && <p className="notice" role="status">{ai.notes} Review it, edit it, then save: nothing is saved or posted until you do.</p>}
      {ai.hooks.length > 0 && (
        <div className="hooks">
          <span className="muted small">Other openings:</span>
          {ai.hooks.map((h) => (
            <button key={h} className="ghost hook" onClick={() => useHook(h)} title="Use as the first line">{h}</button>
          ))}
        </div>
      )}

      <div className="row">
        <button onClick={() => save()} disabled={!dirty || readOnly}>Save changes</button>
        {next.map((st) => (
          <button key={st} className="ghost" onClick={() => save({ status: st })} aria-label={`Move to ${label(st)}`}>
            {st === "scheduled" ? "Schedule" : st === "approved" ? "Approve" : `→ ${label(st)}`}
          </button>
        ))}
        {!readOnly && (
          <button className="ghost" onClick={() => onPatch({ locked: !slot.locked })}>
            {slot.locked ? "Unlock" : "Lock"}
          </button>
        )}
        <span className="spacer" />
        {!["published", "analysed"].includes(slot.status) && <button className="ghost danger" onClick={onDelete}>Delete</button>}
      </div>
    </section>
  );
}
