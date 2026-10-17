import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Venture, type VentureInput } from "../api";
import { useAuth } from "../auth";
import BriefEditor from "../components/BriefEditor";
import VentureForm from "../components/VentureForm";

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

      <BriefEditor ventureId={venture.id} />

      <h3>Research</h3>
      <div className="grid">
        <Link to={`/ventures/${venture.id}/feed`} className="card linkcard">
          <h4>Trend feed</h4>
          <p className="muted small">Topics from RSS, Reddit and Google News, ranked for your niche.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/plan`} className="card linkcard">
          <h4>Content planner</h4>
          <p className="muted small">A weekly or monthly TOFU / MOFU / BOFU calendar built from your setup.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/insights`} className="card linkcard">
          <h4>Performance</h4>
          <p className="muted small">What worked, what didn't, and which posts brought leads.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/publishing`} className="card linkcard">
          <h4>Publishing</h4>
          <p className="muted small">Connect LinkedIn and X so approved posts go out on schedule.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/influencers`} className="card linkcard">
          <h4>Influencer watch</h4>
          <p className="muted small">Follow the voices in your niche and see what they're all talking about.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/communities`} className="card linkcard">
          <h4>Community heat</h4>
          <p className="muted small">Which topics are getting likes and comments in the groups your audience is in.</p>
        </Link>
        <Link to={`/ventures/${venture.id}/replies`} className="card linkcard">
          <h4>Quick replies</h4>
          <p className="muted small">Helpful answers to questions in communities, drafted for you to post yourself.</p>
        </Link>
      </div>
    </>
  );
}
