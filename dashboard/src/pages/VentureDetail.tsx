import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Venture, type VentureInput } from "../api";
import { useAuth } from "../auth";
import VentureForm from "../components/VentureForm";

const UPCOMING = [
  ["Authority Brief", "ICP, niche positioning, content pillars, offer and voice"],
  ["Trend feed", "Daily topics from Google, X, Reddit and RSS filtered to your ICP"],
  ["Content planner", "Weekly and monthly TOFU / MOFU / BOFU calendar"],
  ["Performance", "What worked, what didn't, and leads by post"],
];

export default function VentureDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const [venture, setVenture] = useState<Venture | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const numeric = Number(id);
    if (!Number.isInteger(numeric)) {
      setError("Venture not found");
      return;
    }
    api
      .getVenture(numeric)
      .then(setVenture)
      .catch((err: ApiError) => setError(err.message));
  }, [id]);

  async function save(data: VentureInput) {
    if (!venture) return;
    setVenture(await api.updateVenture(venture.id, data));
    setEditing(false);
  }

  if (error)
    return (
      <>
        <p className="error">{error}</p>
        <Link to="/">← Back to ventures</Link>
      </>
    );
  if (!venture) return <p className="muted">Loading…</p>;

  return (
    <>
      <p>
        <Link to="/">← Ventures</Link>
      </p>
      <div className="page-head">
        <h2>{venture.name}</h2>
        {venture.is_archived && <span className="badge">archived</span>}
        <span className="spacer" />
        {!editing && <button onClick={() => setEditing(true)}>Edit</button>}
      </div>

      <section className="card">
        {editing ? (
          <VentureForm initial={venture} submitLabel="Save changes" onSubmit={save} onCancel={() => setEditing(false)} />
        ) : (
          <dl>
            <dt>Niche</dt>
            <dd>{venture.niche ?? <span className="muted">Not set</span>}</dd>
            <dt>Website</dt>
            <dd>
              {venture.website_url ? (
                <a href={venture.website_url} target="_blank" rel="noopener noreferrer">
                  {venture.website_url}
                </a>
              ) : (
                <span className="muted">Not set</span>
              )}
            </dd>
            <dt>Description</dt>
            <dd>{venture.description ?? <span className="muted">Not set</span>}</dd>
            {user?.role === "admin" && (
              <>
                <dt>Owner</dt>
                <dd>{venture.owner_email}</dd>
              </>
            )}
          </dl>
        )}
      </section>

      <h3>Coming next for this venture</h3>
      <div className="grid">
        {UPCOMING.map(([title, text]) => (
          <div key={title} className="card soon">
            <h4>{title}</h4>
            <p className="muted small">{text}</p>
            <span className="badge">soon</span>
          </div>
        ))}
      </div>
    </>
  );
}
