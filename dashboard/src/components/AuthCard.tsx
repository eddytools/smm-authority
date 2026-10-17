import type { ReactNode } from "react";

export default function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <h1>SMM Authority</h1>
        <p className="muted">{title}</p>
        {children}
      </div>
    </div>
  );
}
