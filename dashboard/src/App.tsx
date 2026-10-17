import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import AdminUsers from "./pages/AdminUsers";
import Login from "./pages/Login";
import Register from "./pages/Register";
import VentureDetail from "./pages/VentureDetail";
import VentureFeed from "./pages/VentureFeed";
import VentureCommunities from "./pages/VentureCommunities";
import VentureInfluencers from "./pages/VentureInfluencers";
import VentureInsights from "./pages/VentureInsights";
import VenturePlan from "./pages/VenturePlan";
import VentureReplies from "./pages/VentureReplies";
import VenturePublishing from "./pages/VenturePublishing";
import Ventures from "./pages/Ventures";

function RequireAuth() {
  const { user, loading } = useAuth();
  if (loading) return <p className="center muted">Loading…</p>;
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

function RequireAdmin() {
  const { user } = useAuth();
  return user?.role === "admin" ? <Outlet /> : <Navigate to="/" replace />;
}

function GuestOnly() {
  const { user, loading } = useAuth();
  if (loading) return <p className="center muted">Loading…</p>;
  return user ? <Navigate to="/" replace /> : <Outlet />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Ventures />} />
          <Route path="ventures/:id" element={<VentureDetail />} />
          <Route path="ventures/:id/feed" element={<VentureFeed />} />
          <Route path="ventures/:id/influencers" element={<VentureInfluencers />} />
          <Route path="ventures/:id/communities" element={<VentureCommunities />} />
          <Route path="ventures/:id/plan" element={<VenturePlan />} />
          <Route path="ventures/:id/insights" element={<VentureInsights />} />
          <Route path="ventures/:id/publishing" element={<VenturePublishing />} />
          <Route path="ventures/:id/replies" element={<VentureReplies />} />
          <Route element={<RequireAdmin />}>
            <Route path="admin/users" element={<AdminUsers />} />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
