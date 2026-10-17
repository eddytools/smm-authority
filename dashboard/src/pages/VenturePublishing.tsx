import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Integration, type Venture } from "../api";

const ENV_HINT: Record<string, string> = {
  linkedin: "SMM_LINKEDIN_CLIENT_ID, SMM_LINKEDIN_CLIENT_SECRET",
  x: "SMM_X_CLIENT_ID, SMM_X_CLIENT_SECRET",
};
const ERRORS: Record<string, string> = {
  denied: "Access wasn't granted, so nothing was connected.",
  expired: "That connection attempt took too long and expired. Please try again.",
  exchange_failed: "The platform didn't accept the connection. Please try again, and if it keeps failing ask your administrator to check the app credentials.",
  not_allowed: "Your account no longer has access to this venture.",
  invalid_state: "That connection link has expired or was already used. Please press Connect again.",
};

export default function VenturePublishing() {
  const vid = Number(useParams().id);
  const [params, setParams] = useSearchParams();
  const [venture, setVenture] = useState<Venture | null>(null);
  const [rows, setRows] = useState<Integration[] | null>(null);
  const [error, setError] = useState(() => ERRORS[params.get("error") ?? ""] ?? "");
  const [notice, setNotice] = useState(() => (params.get("connected") ? `${params.get("connected") === "x" ? "X" : "LinkedIn"} connected.` : ""));
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => setRows(await api.listIntegrations(vid)), [vid]);
  useEffect(() => {
    api.getVenture(vid).then(setVenture).catch((e: Error) => setError(e.message));
    load().catch((e: Error) => setError(e.message));
    if (params.has("connected") || params.has("error")) setParams({}, { replace: true }); // don't keep the banner on refresh
  }, [vid, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(null);
  };

  const connect = (platform: string) =>
    run(platform, async () => {
      const { authorize_url } = await api.connectIntegration(vid, platform);
      window.location.assign(authorize_url); // off to LinkedIn / X to approve; they send the browser back here
    });

  return (
    <>
      <p>
        <Link to={`/ventures/${vid}`}>← {venture?.name ?? "Venture"}</Link>
      </p>
      <div className="page-head">
        <h2>Publishing</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}

      <section className="card">
        <h3>How posting works</h3>
        <ul className="small">
          <li>Only posts you have <strong>approved and scheduled</strong> are ever sent, at the time you set, to the account you connect here.</li>
          <li>You can post any approved post right away with <strong>Publish now</strong> in the planner.</li>
          <li>Failures are retried a few times when they look temporary, then stop and show you the reason. A post is never sent twice.</li>
          <li>If the app was offline and a post is more than a day late, it is held for you instead of going out stale.</li>
          <li>Reddit, Instagram, YouTube, blog and newsletter posts are posted by hand: mark them Published in the planner.</li>
        </ul>
      </section>

      {rows === null && !error && <p className="muted">Loading…</p>}
      <div className="grid">
        {rows?.map((r) => (
          <section key={r.platform} className="card" aria-label={r.label}>
            <h3>
              {r.label}
              {r.connected && <span className={`badge ${r.status === "active" ? "admin" : ""}`}>{r.status === "active" ? "Connected" : "Reconnect needed"}</span>}
            </h3>

            {!r.configured && (
              <p className="muted small">
                Not set up on this server yet. An administrator needs to register a {r.label} developer app and add its credentials ({ENV_HINT[r.platform]}) plus an encryption key
                (<code>SMM_TOKEN_ENCRYPTION_KEY</code>) to the API settings. See the README.
              </p>
            )}

            {r.configured && !r.connected && (
              <>
                <p className="muted small">Connect the {r.label} account this venture should post from. You will approve access on {r.label}'s own site; your password is never shared with this app.</p>
                <button onClick={() => connect(r.platform)} disabled={busy !== null}>{busy === r.platform ? "Opening…" : `Connect ${r.label}`}</button>
              </>
            )}

            {r.connected && (
              <>
                <p>
                  Posting as <strong>{r.account_name}</strong>
                </p>
                {r.status !== "active" && (
                  <p className="error small">{r.label} stopped accepting this connection (it may have expired or been revoked). Reconnect to resume posting.</p>
                )}
                <label className="inline">
                  <input
                    type="checkbox"
                    checked={!!r.auto_publish}
                    onChange={(e) => {
                      const on = e.target.checked;
                      setRows((cur) => cur?.map((x) => (x.platform === r.platform ? { ...x, auto_publish: on } : x)) ?? null); // respond instantly
                      void run(r.platform, async () => {
                        try {
                          await api.updateIntegration(vid, r.platform, on);
                        } catch (err) {
                          await load(); // the server said no: show the real state again
                          throw err;
                        }
                      });
                    }}
                  />{" "}
                  Post scheduled posts automatically
                </label>
                {!r.auto_publish && <p className="muted small">Paused: scheduled posts will wait for you. Publish now still works.</p>}
                <div className="row" style={{ marginTop: ".7rem" }}>
                  {r.status !== "active" && <button onClick={() => connect(r.platform)} disabled={busy !== null}>Reconnect</button>}
                  <button
                    className="ghost danger"
                    disabled={busy !== null}
                    onClick={() => {
                      if (!window.confirm(`Disconnect ${r.label}? Scheduled posts will stop going out automatically. Also remove this app's access in your ${r.label} account settings to fully revoke it.`)) return;
                      void run(r.platform, async () => { await api.disconnectIntegration(vid, r.platform); await load(); setNotice(`${r.label} disconnected.`); });
                    }}
                  >
                    Disconnect
                  </button>
                </div>
              </>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
