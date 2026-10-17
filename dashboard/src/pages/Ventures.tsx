import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Venture, type VentureInput } from "../api";
import { useAuth } from "../auth";
import VentureForm from "../components/VentureForm";

export default function Ventures() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const isAdmin = user?.role === "admin";
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [showArchived, setShowArchived] = useState(false);
  const [ventures, setVentures] = useState<Venture[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setError("");
      setVentures(await api.listVentures(scope, showArchived));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [scope, showArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(data: VentureInput) {
    await api.createVenture(data);
    setCreating(false);
    await load();
  }

  async function toggleArchive(v: Venture) {
    try {
      await api.updateVenture(v.id, { is_archived: !v.is_archived });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(v: Venture) {
    if (!window.confirm(`Delete "${v.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteVenture(v.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <div className="page-head">
        <h2>{scope === "all" ? "All ventures" : "My ventures"}</h2>
        <span className="spacer" />
        {isAdmin && (
          <select value={scope} onChange={(e) => setScope(e.target.value as "mine" | "all")} aria-label="Scope">
            <option value="mine">My ventures</option>
            <option value="all">All users' ventures</option>
          </select>
        )}
        <label className="inline">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived
        </label>
        <button onClick={() => setCreating(true)} disabled={creating}>
          New venture
        </button>
      </div>

      {creating && (
        <section className="card">
          <h3>New venture</h3>
          <VentureForm submitLabel="Create venture" onSubmit={create} onCancel={() => setCreating(false)} />
        </section>
      )}

      {params.get("publishing_error") && <p className="error" role="alert">That connection link has expired or was already used. Open the venture's Publishing page and press Connect again.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {ventures === null && !error && <p className="muted">Loading…</p>}
      {ventures?.length === 0 && !creating && (
        <section className="card empty">
          <p>No ventures yet. A venture is a brand, business or personal project you want to build authority for.</p>
          <button onClick={() => setCreating(true)}>Create your first venture</button>
        </section>
      )}

      <div className="grid">
        {ventures?.map((v) => (
          <article key={v.id} className={`card venture ${v.is_archived ? "archived" : ""}`}>
            <h3>
              <Link to={`/ventures/${v.id}`}>{v.name}</Link>
              {v.is_archived && <span className="badge">archived</span>}
            </h3>
            {v.niche && <p className="niche">{v.niche}</p>}
            {v.description && <p className="muted clamp">{v.description}</p>}
            {scope === "all" && <p className="small muted">Owner: {v.owner_email}</p>}
            <div className="row actions">
              <Link to={`/ventures/${v.id}`} className="btn">
                Open
              </Link>
              <button className="ghost" onClick={() => toggleArchive(v)}>
                {v.is_archived ? "Restore" : "Archive"}
              </button>
              <button className="ghost danger" onClick={() => remove(v)}>
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
