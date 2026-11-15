// Shared UI building blocks (Tailwind). Every page is built from these, so the
// look stays consistent: change it here, not page by page.

import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { Link } from "react-router-dom";
import { label as fmtLabel } from "../lib/format";
import { Icon, type IconName } from "./icons";

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-700 text-white shadow-sm hover:bg-brand-800 disabled:bg-brand-300 disabled:shadow-none",
  secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 shadow-sm hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-rose-600 text-white shadow-sm hover:bg-rose-700 disabled:bg-rose-300",
  ghost: "text-brand-700 hover:bg-brand-50 disabled:text-slate-400",
};
const SIZES = { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-sm", lg: "h-12 px-5 text-base" };

export function Button({
  variant = "primary",
  size = "md",
  icon,
  busy,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZES; icon?: IconName; busy?: boolean }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed ${SIZES[size]} ${VARIANTS[variant]} ${className}`}
      disabled={busy || rest.disabled}
      {...rest}
    >
      {busy ? (
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
      ) : icon && <Icon name={icon} className="h-4 w-4" />}
      {children}
    </button>
  );
}

// A link that looks like a button
export function ButtonLink({ to, variant = "primary", size = "md", icon, className = "", children }: {
  to: string; variant?: Variant; size?: keyof typeof SIZES; icon?: IconName; className?: string; children: ReactNode;
}) {
  return (
    <Link to={to} className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors ${SIZES[size]} ${VARIANTS[variant]} ${className}`}>
      {icon && <Icon name={icon} className="h-4 w-4" />}
      {children}
    </Link>
  );
}

function Field({ label, hint, children }: { label?: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block text-sm">
      {label && <span className="mb-1.5 block font-medium text-slate-700">{label}</span>}
      {children}
      {hint && <span className="mt-1.5 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const control =
  "block w-full rounded-lg border-0 bg-white px-3 py-2.5 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 outline-none placeholder:text-slate-400 transition focus:ring-2 focus:ring-brand-600 disabled:bg-slate-50 disabled:text-slate-500";

export function Input({ label, hint, className = "", ...rest }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: ReactNode }) {
  return (
    <Field label={label} hint={hint}>
      <input className={`${control} ${className}`} {...rest} />
    </Field>
  );
}

export function TextArea({ label, hint, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: ReactNode }) {
  return (
    <Field label={label} hint={hint}>
      <textarea className={control} rows={3} {...rest} />
    </Field>
  );
}

export function Select({
  label,
  hint,
  options,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  hint?: ReactNode;
  options: { value: string; label: string }[];
}) {
  return (
    <Field label={label} hint={hint}>
      <select className={`${control} pr-8`} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Checkbox({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm text-slate-700">
      <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 accent-brand-700" {...rest} />
      <span>{label}</span>
    </label>
  );
}

export function Card({ title, description, actions, children, className = "", padded = true }: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-card ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={padded ? "p-4 sm:p-5" : ""}>{children}</div>
    </section>
  );
}

export function PageTitle({ children, sub, actions, back }: {
  children: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
}) {
  return (
    <div className="mb-6">
      {back && (
        <Link to={back.to} className="mb-2 inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800">
          <Icon name="arrowLeft" className="h-4 w-4" /> {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{children}</h1>
          {sub && <div className="mt-1 text-sm text-slate-500">{sub}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

const ALERT = {
  error: { style: "border-rose-200 bg-rose-50 text-rose-800", icon: "xCircle" },
  success: { style: "border-emerald-200 bg-emerald-50 text-emerald-800", icon: "checkCircle" },
  info: { style: "border-brand-200 bg-brand-50 text-brand-900", icon: "info" },
  warning: { style: "border-amber-200 bg-amber-50 text-amber-900", icon: "alert" },
} as const;

export function Alert({ kind = "error", title, children }: { kind?: keyof typeof ALERT; title?: ReactNode; children: ReactNode }) {
  if (!children) return null;
  const a = ALERT[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`flex gap-2.5 rounded-lg border px-3.5 py-3 text-sm ${a.style}`}>
      <Icon name={a.icon} className="mt-px h-4 w-4" />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ text = "Loading…" }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" />
      {text}
    </div>
  );
}

export function Empty({ icon = "inbox", title, children, action }: { icon?: IconName; title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      <span className="mb-3 grid h-11 w-11 place-items-center rounded-full bg-slate-100 text-slate-400">
        <Icon name={icon} />
      </span>
      {title && <p className="font-medium text-slate-900">{title}</p>}
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const BADGE = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  red: "bg-rose-50 text-rose-700 ring-rose-600/20",
  blue: "bg-brand-50 text-brand-700 ring-brand-600/20",
  grey: "bg-slate-100 text-slate-600 ring-slate-500/20",
  purple: "bg-violet-50 text-violet-700 ring-violet-600/20",
};
const DOT = {
  green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-rose-500",
  blue: "bg-brand-500", grey: "bg-slate-400", purple: "bg-violet-500",
};

export function Badge({ color = "grey", dot, children }: { color?: keyof typeof BADGE; dot?: boolean; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${BADGE[color]}`}>
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${DOT[color]}`} />}
      {children}
    </span>
  );
}

const STATUS_COLOR: Record<string, keyof typeof BADGE> = {
  placed: "amber", accepted: "blue", collected: "purple", received: "purple",
  processing: "purple", ready: "blue", out_for_delivery: "purple", delivered: "green",
  declined: "red", cancelled: "grey",
  pending: "amber", approved: "green", rejected: "red", missing: "grey",
  open: "amber", investigating: "blue", resolved: "green", dismissed: "grey",
  assigned: "blue", picked_up: "purple", completed: "green",
  paid: "green", failed: "red",
  low: "grey", medium: "amber", high: "red", critical: "red",
};

// Plain-language names for statuses (the API uses short codes)
const STATUS_TEXT: Record<string, string> = {
  received: "At the laundry",
  processing: "Being cleaned",
  ready: "Ready for delivery",
  pending: "Pending review",
};

export function statusText(status: string): string {
  return STATUS_TEXT[status] ?? fmtLabel(status);
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge color={STATUS_COLOR[status] ?? "grey"} dot>{statusText(status)}</Badge>;
}

export function Stars({ value, count }: { value: number | null; count?: number }) {
  if (value == null) return <span className="text-xs text-slate-500">No ratings yet</span>;
  const full = Math.round(value);
  return (
    <span className="inline-flex items-center gap-1 text-sm" title={`${value.toFixed(1)} out of 5`}>
      <span className="inline-flex" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <Icon key={i} name="star" className={`h-3.5 w-3.5 ${i < full ? "fill-amber-400 text-amber-400" : "fill-slate-200 text-slate-200"}`} />
        ))}
      </span>
      <span className="text-xs font-medium text-slate-700">{value.toFixed(1)}</span>
      {count != null && <span className="text-xs text-slate-500">({count})</span>}
    </span>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr] sm:gap-y-2.5">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="mb-2 font-medium text-slate-900 sm:mb-0">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

// A row in a list that opens something (orders, jobs, incidents…)
export function ListRow({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-slate-50 sm:px-5">
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">{children}</div>
      <Icon name="chevronRight" className="h-4 w-4 text-slate-300 group-hover:text-slate-500" />
    </Link>
  );
}

// Big number on a dashboard
export function Stat({ label, value, icon, tone = "slate" }: { label: string; value: ReactNode; icon?: IconName; tone?: "slate" | "brand" | "amber" | "violet" | "emerald" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-600", brand: "bg-brand-50 text-brand-700", amber: "bg-amber-50 text-amber-700",
    violet: "bg-violet-50 text-violet-700", emerald: "bg-emerald-50 text-emerald-700",
  };
  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-card">
      {icon && <span className={`grid h-10 w-10 place-items-center rounded-lg ${tones[tone]}`}><Icon name={icon} /></span>}
      <div>
        <p className="text-xs font-medium text-slate-500">{label}</p>
        <p className="text-2xl font-semibold tracking-tight text-slate-900">{value}</p>
      </div>
    </div>
  );
}

// Segmented tabs
export function Tabs({ items, value, onChange }: { items: { label: string; count?: number }[]; value: number; onChange: (i: number) => void }) {
  return (
    <div role="tablist" className="inline-flex rounded-lg bg-slate-100 p-1">
      {items.map((t, i) => (
        <button key={t.label} role="tab" aria-selected={value === i} onClick={() => onChange(i)}
          className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${value === i ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
          {t.label}
          {t.count != null && t.count > 0 && <span className="rounded-full bg-brand-100 px-1.5 text-xs text-brand-800">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
