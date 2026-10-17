import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type Role, type User } from "../api";
import { useAuth } from "../auth";

const VENDOR_NAME: Record<string, string> = { anthropic: "Anthropic (Claude)", openai: "OpenAI or an OpenAI-compatible server", gemini: "Google Gemini" };

function AiCard() {
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.aiStatus>> | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.aiStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  if (!status) return null;
  async function test() {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.aiTest();
      setResult({ ok: true, text: `Working: ${r.model} answered (${r.input_tokens + r.output_tokens} tokens used).` });
    } catch (err) {
      setResult({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <h3>AI</h3>
      {status.configured ? (
        <p className="small">
          Using <strong>{VENDOR_NAME[status.provider ?? ""] ?? status.provider}</strong>, model <code>{status.model}</code>
          {status.base_url ? <> at <code>{status.base_url}</code></> : null}. Each non-admin user gets {status.daily_limit_per_user} AI requests per day.
        </p>
      ) : (
        <p className="small">No AI vendor is configured, so drafting, scoring, quick replies and brief suggestions are off. Set <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or <code>GEMINI_API_KEY</code> (plus <code>SMM_AI_MODEL</code> for OpenAI and Gemini) on the server and restart it.</p>
      )}
      {status.configured && (
        <p>
          <button className="ghost" disabled={busy} onClick={test}>{busy ? "Testing…" : "Test the AI connection"}</button>{" "}
          {result && <span className={result.ok ? "small" : "error"} role="status">{result.text}</span>}
        </p>
      )}
    </section>
  );
}

export default function AdminUsers() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "user" as Role });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setUsers(await api.listUsers());
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function update(id: number, data: Partial<{ role: Role; is_active: boolean }>) {
    try {
      setError("");
      await api.updateUser(id, data);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createUser(form);
      setForm({ name: "", email: "", password: "", role: "user" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h2>Users</h2>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <AiCard />

      <section className="card">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users?.map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id}>
                  <td>
                    {u.name} {self && <span className="muted small">(you)</span>}
                  </td>
                  <td>{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      disabled={self}
                      aria-label={`Role for ${u.email}`}
                      onChange={(e) => update(u.id, { role: e.target.value as Role })}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </td>
                  <td>{u.is_active ? "Active" : <span className="muted">Deactivated</span>}</td>
                  <td>
                    <button className="ghost" disabled={self} onClick={() => update(u.id, { is_active: !u.is_active })}>
                      {u.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {users === null && !error && <p className="muted">Loading…</p>}
      </section>

      <section className="card">
        <h3>Add user</h3>
        <form onSubmit={create} className="inline-form">
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <input
            type="email"
            placeholder="Email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
          <input
            type="password"
            placeholder="Temporary password (min 8)"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            minLength={8}
          />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <button disabled={busy}>Add user</button>
        </form>
      </section>
    </>
  );
}
