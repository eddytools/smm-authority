import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <>
      <header className="topbar">
        <strong className="brand">SMM Authority</strong>
        <nav>
          <NavLink to="/" end>
            Ventures
          </NavLink>
          {user?.role === "admin" && <NavLink to="/admin/users">Users</NavLink>}
        </nav>
        <span className="spacer" />
        <span className="muted who">
          {user?.name} <span className={`badge ${user?.role}`}>{user?.role}</span>
        </span>
        <button className="ghost" onClick={logout}>
          Sign out
        </button>
      </header>
      <main className="container">
        <Outlet />
      </main>
    </>
  );
}
