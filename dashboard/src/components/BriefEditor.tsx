import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import { api, PLATFORMS, type BriefData, type BriefVersionSummary, type Platform } from "../api";

// Form values are plain strings. List fields are one item per line.
type Fields = Record<string, string>;
interface PlatformState {
  enabled: boolean;
  cadence: number;
  primary: boolean;
  reason: string;
}
type Platforms = Record<Platform, PlatformState>;

const lines = (s: string): string[] =>
  s
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
const opt = (s: string): string | null => (s.trim() === "" ? null : s.trim());
const SAMPLE_SEP = "\n---\n";

const emptyPlatforms = (): Platforms =>
  Object.fromEntries(PLATFORMS.map((p) => [p, { enabled: false, cadence: 3, primary: false, reason: "" }])) as Platforms;

function fromData(d: BriefData | null): { fields: Fields; platforms: Platforms } {
  const platforms = emptyPlatforms();
  d?.platforms.forEach((p) => {
    platforms[p.platform] = { enabled: true, cadence: p.cadence_per_week, primary: p.is_primary, reason: p.reason ?? "" };
  });
  const j = (a?: string[]) => (a ?? []).join("\n");
  return {
    platforms,
    fields: {
      "icp.industry": d?.icp.industry ?? "",
      "icp.company_size": d?.icp.company_size ?? "",
      "icp.roles": j(d?.icp.roles),
      "icp.pains": j(d?.icp.pains),
      "icp.goals": j(d?.icp.goals),
      "icp.objections": j(d?.icp.objections),
      "icp.channels": j(d?.icp.channels),
      "ideation.niche_statement": d?.ideation.niche_statement ?? "",
      "ideation.unique_angle": d?.ideation.unique_angle ?? "",
      "ideation.pillars": j(d?.ideation.pillars),
      "ideation.proof_assets": j(d?.ideation.proof_assets),
      "ideation.opinions": j(d?.ideation.opinions),
      "offer.offer": d?.offer.offer ?? "",
      "offer.lead_magnets": j(d?.offer.lead_magnets),
      "offer.cta_url": d?.offer.cta_url ?? "",
      "offer.booking_url": d?.offer.booking_url ?? "",
      "voice.tone": d?.voice.tone ?? "",
      "voice.dos": j(d?.voice.dos),
      "voice.donts": j(d?.voice.donts),
      "voice.writing_samples": (d?.voice.writing_samples ?? []).join(SAMPLE_SEP),
    },
  };
}

function toIdeation(f: Fields): BriefData["ideation"] {
  return {
    niche_statement: opt(f["ideation.niche_statement"]),
    unique_angle: opt(f["ideation.unique_angle"]),
    pillars: lines(f["ideation.pillars"]),
    proof_assets: lines(f["ideation.proof_assets"]),
    opinions: lines(f["ideation.opinions"]),
  };
}

function toData(f: Fields, platforms: Platforms): BriefData {
  return {
    icp: {
      industry: opt(f["icp.industry"]),
      company_size: opt(f["icp.company_size"]),
      roles: lines(f["icp.roles"]),
      pains: lines(f["icp.pains"]),
      goals: lines(f["icp.goals"]),
      objections: lines(f["icp.objections"]),
      channels: lines(f["icp.channels"]),
    },
    ideation: toIdeation(f),
    offer: {
      offer: opt(f["offer.offer"]),
      lead_magnets: lines(f["offer.lead_magnets"]),
      cta_url: opt(f["offer.cta_url"]),
      booking_url: opt(f["offer.booking_url"]),
    },
    voice: {
      tone: opt(f["voice.tone"]),
      dos: lines(f["voice.dos"]),
      donts: lines(f["voice.donts"]),
      writing_samples: f["voice.writing_samples"]
        .split(/\n-{3,}\n/)
        .map((s) => s.trim())
        .filter(Boolean),
    },
    platforms: PLATFORMS.filter((p) => platforms[p].enabled).map((p) => ({
      platform: p,
      cadence_per_week: platforms[p].cadence,
      is_primary: platforms[p].primary,
      reason: opt(platforms[p].reason),
    })),
  };
}

export default function BriefEditor({ ventureId }: { ventureId: number }) {
  const [{ fields, platforms }, setState] = useState(() => fromData(null));
  const [version, setVersion] = useState<number | null>(null);
  const [versions, setVersions] = useState<BriefVersionSummary[]>([]);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"save" | "ai" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const [brief, list] = await Promise.all([api.getBrief(ventureId), api.listBriefVersions(ventureId)]);
      setState(fromData(brief?.data ?? null));
      setVersion(brief?.version ?? null);
      setVersions(list);
      setDirty(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [ventureId]);

  useEffect(() => {
    void load();
  }, [load]);

  const setField = (key: string) => (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setState((s) => ({ ...s, fields: { ...s.fields, [key]: e.target.value } }));
    setDirty(true);
    setNotice("");
  };

  const setPlatform = (p: Platform, patch: Partial<PlatformState>) => {
    setState((s) => {
      const next = { ...s.platforms, [p]: { ...s.platforms[p], ...patch } };
      if (patch.primary) PLATFORMS.forEach((o) => o !== p && (next[o] = { ...next[o], primary: false }));
      if (patch.enabled === false) next[p].primary = false;
      return { ...s, platforms: next };
    });
    setDirty(true);
    setNotice("");
  };

  async function save() {
    setBusy("save");
    setError("");
    try {
      const saved = await api.saveBrief(ventureId, toData(fields, platforms));
      setVersion(saved.version);
      setVersions(await api.listBriefVersions(ventureId));
      setDirty(false);
      setNotice(`Saved as version ${saved.version}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function suggest() {
    setBusy("ai");
    setError("");
    setNotice("");
    try {
      const data = toData(fields, platforms);
      const s = await api.suggestBrief(ventureId, { icp: data.icp, offer: data.offer, voice: data.voice, ideation: data.ideation });
      setState((cur) => {
        const merged = fromData({ ...data, ideation: s.ideation, platforms: s.platforms });
        // keep anything the user typed for fields the model left empty
        for (const k of Object.keys(merged.fields)) if (!merged.fields[k] && cur.fields[k]) merged.fields[k] = cur.fields[k];
        return merged;
      });
      setDirty(true);
      setNotice(`AI draft applied to Ideation and Platforms. Review and edit, then save. ${s.rationale}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function restore(v: number) {
    try {
      const b = await api.getBriefVersion(ventureId, v);
      setState(fromData(b.data));
      setDirty(true);
      setNotice(`Loaded version ${v}. Save to make it the current version.`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const text = (key: string, label: string, hint?: string) => (
    <label>
      {label} {hint && <span className="muted small">{hint}</span>}
      <input value={fields[key]} onChange={setField(key)} />
    </label>
  );
  const area = (key: string, label: string, hint = "one per line", rows = 3) => (
    <label>
      {label} <span className="muted small">({hint})</span>
      <textarea rows={rows} value={fields[key]} onChange={setField(key)} />
    </label>
  );

  if (loading) return <p className="muted">Loading setup…</p>;

  return (
    <section className="card">
      <div className="page-head">
        <div>
          <h3>Authority setup</h3>
          <p className="muted small">
            {version ? `Current version ${version}` : "Not completed yet"}
            {dirty && " · unsaved changes"}
          </p>
        </div>
        <span className="spacer" />
        {versions.length > 1 && (
          <select aria-label="Load an earlier version" value="" onChange={(e) => e.target.value && restore(Number(e.target.value))}>
            <option value="">History…</option>
            {versions.map((v) => (
              <option key={v.version} value={v.version}>
                v{v.version} · {new Date(v.created_at).toLocaleDateString()}
              </option>
            ))}
          </select>
        )}
        <button className="ghost" onClick={suggest} disabled={busy !== null}>
          {busy === "ai" ? "Thinking…" : "Suggest with AI"}
        </button>
        <button onClick={save} disabled={busy !== null || (!dirty && version !== null)}>
          {busy === "save" ? "Saving…" : "Save new version"}
        </button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <details open>
        <summary>1. Ideal customer (ICP)</summary>
        <div className="two-col">
          {text("icp.industry", "Industry")}
          {text("icp.company_size", "Company size")}
        </div>
        {area("icp.roles", "Roles / job titles")}
        {area("icp.pains", "Pain points")}
        {area("icp.goals", "Goals")}
        {area("icp.objections", "Objections before buying")}
        {area("icp.channels", "Where they spend time", "e.g. LinkedIn, r/startups, newsletters")}
      </details>

      <details open>
        <summary>2. Authority ideation</summary>
        {text("ideation.niche_statement", "Niche statement", "who you help and how")}
        {text("ideation.unique_angle", "Unique angle")}
        {area("ideation.pillars", "Content pillars", "3 to 5, one per line", 4)}
        {area("ideation.proof_assets", "Proof assets", "case studies, numbers, testimonials")}
        {area("ideation.opinions", "Opinions you will take a stand on")}
      </details>

      <details open>
        <summary>3. Offer and funnel</summary>
        {text("offer.offer", "Main offer")}
        {area("offer.lead_magnets", "Lead magnets", "checklist, template…")}
        <div className="two-col">
          <label>
            CTA link
            <input type="url" placeholder="https://" value={fields["offer.cta_url"]} onChange={setField("offer.cta_url")} />
          </label>
          <label>
            Booking link
            <input type="url" placeholder="https://" value={fields["offer.booking_url"]} onChange={setField("offer.booking_url")} />
          </label>
        </div>
      </details>

      <details open>
        <summary>4. Voice</summary>
        {text("voice.tone", "Tone", "e.g. direct, warm, no jargon")}
        <div className="two-col">
          {area("voice.dos", "Do")}
          {area("voice.donts", "Don't")}
        </div>
        {area("voice.writing_samples", "Writing samples", "separate samples with a line containing ---", 5)}
      </details>

      <details open>
        <summary>5. Platforms</summary>
        <table>
          <thead>
            <tr>
              <th>Use</th>
              <th>Platform</th>
              <th>Posts / week</th>
              <th>Primary</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {PLATFORMS.map((p) => {
              const s = platforms[p];
              return (
                <tr key={p}>
                  <td>
                    <input type="checkbox" aria-label={`Use ${p}`} checked={s.enabled} onChange={(e) => setPlatform(p, { enabled: e.target.checked })} />
                  </td>
                  <td>{p}</td>
                  <td>
                    <input
                      type="number"
                      min={1}
                      max={21}
                      aria-label={`${p} posts per week`}
                      value={s.cadence}
                      disabled={!s.enabled}
                      onChange={(e) => setPlatform(p, { cadence: Math.min(21, Math.max(1, Number(e.target.value) || 1)) })}
                    />
                  </td>
                  <td>
                    <input type="radio" name="primary-platform" aria-label={`${p} is primary`} checked={s.primary} disabled={!s.enabled} onChange={() => setPlatform(p, { primary: true })} />
                  </td>
                  <td className="small muted">{s.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </section>
  );
}
