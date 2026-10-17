import { useState, type FormEvent } from "react";
import type { VentureInput, Venture } from "../api";

interface Props {
  initial?: Venture;
  submitLabel: string;
  onSubmit: (data: VentureInput) => Promise<void>;
  onCancel?: () => void;
}

const blankToNull = (v: string) => (v.trim() === "" ? null : v.trim());

export default function VentureForm({ initial, submitLabel, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [niche, setNiche] = useState(initial?.niche ?? "");
  const [website, setWebsite] = useState(initial?.website_url ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit({
        name: name.trim(),
        niche: blankToNull(niche),
        website_url: blankToNull(website),
        description: blankToNull(description),
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <label>
        Venture name
        <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoFocus />
      </label>
      <label>
        Niche <span className="muted small">(who you serve / what you're known for)</span>
        <input value={niche} onChange={(e) => setNiche(e.target.value)} maxLength={200} />
      </label>
      <label>
        Website
        <input type="url" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://" />
      </label>
      <label>
        Description
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={2000} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="row">
        <button disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
        {onCancel && (
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
