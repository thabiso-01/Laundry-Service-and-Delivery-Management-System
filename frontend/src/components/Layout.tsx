import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./ui";

const NAV: Record<Role, [string, string][]> = {
  customer: [["/search", "Find a laundry"], ["/orders", "My orders"], ["/incidents", "My reports"]],
  business: [["/business", "Orders"], ["/business/scan", "Scan a bag"], ["/business/services", "Services"], ["/business/staff", "Staff"],
    ["/business/profile", "Profile"], ["/documents", "Documents"]],
  driver: [["/driver", "Jobs"], ["/documents", "Documents"], ["/incidents", "My reports"]],
  admin: [["/admin", "Verification"], ["/admin/incidents", "Incidents"], ["/admin/routes", "Route alerts"]],
};

function UnreadBadge() {
  const [unread, setUnread] = useState(0);
  const location = useLocation();
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<{ unread: number }>("/api/notifications?limit=1")
        .then((r) => alive && setUnread(r.unread))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [location.pathname]);
  return (
    <NavLink to="/notifications" className="relative rounded-lg px-2 py-1 text-slate-600 hover:bg-slate-100" title="Notifications">
      <span aria-hidden>🔔</span>
      <span className="sr-only">Notifications</span>
      {unread > 0 && (
        <span className="absolute -right-1 -top-1 rounded-full bg-rose-600 px-1.5 text-[10px] font-bold text-white">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </NavLink>
  );
}

export function Layout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const links = me && !me.must_change_password ? NAV[me.role] : [];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <Link to="/" className="text-lg font-bold text-sky-700">
            LaundryConnect
          </Link>
          <nav className="hidden flex-1 gap-1 md:flex">
            {links.map(([to, text]) => (
              <NavLink
                key={to}
                to={to}
                end
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-sky-50 font-medium text-sky-800" : "text-slate-600 hover:bg-slate-100"}`
                }
              >
                {text}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {me ? (
              <>
                {!me.must_change_password && <UnreadBadge />}
                <NavLink to="/security" className="hidden text-sm text-slate-600 hover:underline sm:block" title="Account & privacy">
                  {me.full_name.split(" ")[0]}
                </NavLink>
                <button
                  className="rounded-lg px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
                  onClick={() => {
                    logout();
                    navigate("/login");
                  }}
                >
                  Log out
                </button>
                {links.length > 0 && (
                  <button className="rounded-lg px-2 py-1 md:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
                    ☰
                  </button>
                )}
              </>
            ) : (
              <>
                <Link to="/search" className="text-sm text-slate-600 hover:underline">Find a laundry</Link>
                <Link to="/login" className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-medium text-white">Log in</Link>
              </>
            )}
          </div>
        </div>
        {open && (
          <nav className="border-t border-slate-100 px-4 py-2 md:hidden">
            {[...links, ["/security", "Account & privacy"] as [string, string]].map(([to, text]) => (
              <NavLink key={to} to={to} end onClick={() => setOpen(false)} className="block rounded-lg px-2 py-2 text-sm text-slate-700">
                {text}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}

// Only lets the given roles in (SEC-019 on the screen side; the API enforces it too)
export function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!me) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (me.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  if (roles && !roles.includes(me.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}
