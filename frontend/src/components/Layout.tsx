import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon, Logo, type IconName } from "./icons";
import { ThemeToggle } from "./ThemeToggle";
import { Spinner } from "./ui";

type NavItem = { to: string; text: string; icon: IconName; end?: boolean };

const NAV: Record<Role, NavItem[]> = {
  customer: [
    { to: "/search", text: "Find a laundry", icon: "search" },
    { to: "/orders", text: "My orders", icon: "package" },
    { to: "/incidents", text: "Help & reports", icon: "flag" },
  ],
  business: [
    { to: "/business", text: "Orders", icon: "inbox", end: true },
    { to: "/business/scan", text: "Scan a bag", icon: "scan" },
    { to: "/business/services", text: "Services & prices", icon: "tag" },
    { to: "/business/staff", text: "Staff", icon: "users" },
    { to: "/business/profile", text: "Business profile", icon: "store" },
    { to: "/documents", text: "Documents", icon: "file" },
    { to: "/incidents", text: "Help & reports", icon: "flag" },
  ],
  driver: [
    { to: "/driver", text: "Jobs", icon: "truck", end: true },
    { to: "/documents", text: "Documents", icon: "file" },
    { to: "/incidents", text: "Help & reports", icon: "flag" },
  ],
  admin: [
    { to: "/admin", text: "Verification", icon: "shield", end: true },
    { to: "/admin/incidents", text: "Incidents", icon: "flag" },
    { to: "/admin/routes", text: "Route alerts", icon: "route" },
  ],
};

const ROLE_NAME: Record<Role, string> = { customer: "Customer", business: "Laundry", driver: "Driver", admin: "Administrator" };

function useUnread() {
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
  return unread;
}

function Bell() {
  const unread = useUnread();
  return (
    <NavLink to="/notifications" title="Notifications"
      className={({ isActive }) => `relative grid h-9 w-9 place-items-center rounded-lg transition ${isActive ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"}`}>
      <Icon name="bell" />
      <span className="sr-only">Notifications{unread > 0 && ` (${unread} unread)`}</span>
      {unread > 0 && (
        <span className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-rose-600 px-1 text-center text-[10px] leading-4 font-semibold text-white ring-2 ring-surface">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </NavLink>
  );
}

function Initials({ name }: { name: string }) {
  const letters = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
  return <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800">{letters}</span>;
}

function AccountMenu() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (!me) return null;
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu"
        className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 text-left transition hover:bg-slate-100">
        <Initials name={me.full_name} />
        <span className="hidden leading-tight sm:block">
          <span className="block text-sm font-medium text-slate-800">{me.full_name.split(" ")[0]}</span>
          <span className="block text-xs text-slate-500">{ROLE_NAME[me.role]}</span>
        </span>
        <Icon name="chevronDown" className="hidden h-4 w-4 text-slate-400 sm:block" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-2 w-60 overflow-hidden rounded-xl border border-slate-200 bg-surface shadow-raised">
          <div className="border-b border-slate-100 px-4 py-3">
            <p className="truncate text-sm font-medium text-slate-900">{me.full_name}</p>
            <p className="truncate text-xs text-slate-500">{me.email}</p>
          </div>
          {!me.must_change_password && (
            <Link to="/security" role="menuitem" className="flex items-center gap-2.5 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50">
              <Icon name="lock" className="h-4 w-4 text-slate-400" /> Account & privacy
            </Link>
          )}
          <button role="menuitem" onClick={() => { logout(); navigate("/login"); }}
            className="flex w-full items-center gap-2.5 border-t border-slate-100 px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50">
            <Icon name="logout" className="h-4 w-4 text-slate-400" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}

function SideNav({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <nav className="space-y-0.5" aria-label="Main">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end ?? true} onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${isActive ? "bg-brand-600 text-white shadow-sm shadow-brand-600/25" : "text-slate-600 hover:bg-brand-50 hover:text-brand-800"}`}>
          {({ isActive }) => (
            <>
              <Icon name={item.icon} className={`h-[18px] w-[18px] ${isActive ? "text-white" : "text-slate-400"}`} />
              {item.text}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

// Signed-in app: sidebar on desktop, slide-in menu on phones
function AppShell() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  const items = me && !me.must_change_password ? NAV[me.role] : [];

  return (
    <div className="min-h-screen bg-canvas">
      {/* Desktop sidebar */}
      <aside className="no-print fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-slate-100 bg-surface lg:flex">
        <div className="flex h-16 items-center px-5"><Link to="/"><Logo /></Link></div>
        <div className="flex-1 overflow-y-auto px-3 py-4"><SideNav items={items} /></div>
        <div className="border-t border-slate-100 px-5 py-4 text-xs text-slate-400">
          <span className="inline-flex items-center gap-1.5"><Icon name="shield" className="h-3.5 w-3.5" /> Every handover verified</span>
        </div>
      </aside>

      {/* Phone menu */}
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 animate-fade bg-ink-900/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85%] animate-slide-in flex-col bg-surface shadow-xl">
            <div className="flex h-16 items-center justify-between px-4">
              <Logo />
              <button className="grid h-9 w-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-100" onClick={() => setOpen(false)} aria-label="Close menu">
                <Icon name="x" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-2">
              <SideNav items={[...items, ...(items.length ? [
                { to: "/notifications", text: "Notifications", icon: "bell" as IconName },
                { to: "/security", text: "Account & privacy", icon: "lock" as IconName },
              ] : [])]} />
            </div>
            <button onClick={() => { logout(); navigate("/login"); }}
              className="m-3 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-rose-50 hover:text-rose-700">
              <Icon name="logout" className="h-[18px] w-[18px] text-slate-400" /> Log out
            </button>
          </div>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="no-print sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-slate-200 bg-surface px-4 shadow-sm sm:px-6">
          <Link to="/" className="lg:hidden"><Logo /></Link>
          <div className="ml-auto flex items-center gap-1.5">
            <ThemeToggle />
            {me && !me.must_change_password && <Bell />}
            <AccountMenu />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 pt-6 pb-28 sm:px-6 sm:pt-8 lg:pb-8">
          <div key={location.pathname} className="animate-rise"><Outlet /></div>
        </main>
      </div>
      {me && !me.must_change_password && <TabBar role={me.role} onMore={() => setOpen(true)} moreOpen={open} />}
    </div>
  );
}

// Phone-style tab bar along the bottom of the screen (phones and small tablets)
const TABS: Record<Role, NavItem[]> = {
  customer: [
    { to: "/search", text: "Home", icon: "home" },
    { to: "/orders", text: "Orders", icon: "package" },
    { to: "/notifications", text: "Alerts", icon: "bell" },
  ],
  business: [
    { to: "/business", text: "Orders", icon: "inbox", end: true },
    { to: "/business/scan", text: "Scan", icon: "scan" },
    { to: "/notifications", text: "Alerts", icon: "bell" },
  ],
  driver: [
    { to: "/driver", text: "Jobs", icon: "truck", end: true },
    { to: "/notifications", text: "Alerts", icon: "bell" },
    { to: "/incidents", text: "Help", icon: "flag" },
  ],
  admin: [
    { to: "/admin", text: "Verify", icon: "shield", end: true },
    { to: "/admin/incidents", text: "Incidents", icon: "flag" },
    { to: "/admin/routes", text: "Routes", icon: "route" },
  ],
};

function TabBar({ role, onMore, moreOpen }: { role: Role; onMore: () => void; moreOpen: boolean }) {
  return (
    <nav aria-label="Tabs" className="no-print fixed inset-x-0 bottom-0 z-30 border-t border-slate-100 bg-surface/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-4px_20px_-8px_rgb(30_41_99/0.15)] backdrop-blur lg:hidden">
      <div className="mx-auto grid max-w-md grid-cols-4">
        {TABS[role].map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end ?? true}
            className={({ isActive }) => `flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium ${isActive ? "text-brand-600" : "text-slate-400"}`}>
            {({ isActive }) => (
              <>
                <span className={`grid h-7 w-12 place-items-center rounded-full transition ${isActive ? "bg-brand-50" : ""}`}>
                  <Icon name={t.icon} className="h-5 w-5" />
                </span>
                {t.text}
              </>
            )}
          </NavLink>
        ))}
        <button type="button" onClick={onMore} aria-expanded={moreOpen}
          className={`flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium ${moreOpen ? "text-brand-600" : "text-slate-400"}`}>
          <span className={`grid h-7 w-12 place-items-center rounded-full ${moreOpen ? "bg-brand-50" : ""}`}><Icon name="menu" className="h-5 w-5" /></span>
          More
        </button>
      </div>
    </nav>
  );
}

// Visitors who aren't signed in: simple top bar
function PublicShell() {
  const location = useLocation();
  const wide = location.pathname === "/";
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-surface shadow-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <Link to="/"><Logo /></Link>
          <nav className="ml-auto flex items-center gap-1 sm:gap-2">
            <ThemeToggle />
            <NavLink to="/search" className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 sm:block">Find a laundry</NavLink>
            <NavLink to="/login" className="rounded-lg px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100">Log in</NavLink>
            <NavLink to="/register" className="rounded-full bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-brand-600/25 hover:bg-deep">Sign up</NavLink>
          </nav>
        </div>
      </header>
      <main className={wide ? "flex-1" : "mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6"}>
        <div key={location.pathname} className="animate-rise"><Outlet /></div>
      </main>
      <footer className="border-t border-slate-200 bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-6 text-sm text-slate-500 sm:px-6">
          <span>© {new Date().getFullYear()} LaundryConnect · South Africa</span>
          <span className="inline-flex items-center gap-1.5"><Icon name="lock" className="h-4 w-4" /> Your data is protected under POPIA</span>
        </div>
      </footer>
    </div>
  );
}

export function Layout() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  return me ? <AppShell /> : <PublicShell />;
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
