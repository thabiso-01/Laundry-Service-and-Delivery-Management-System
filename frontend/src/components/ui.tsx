// Small shared UI building blocks (Tailwind).

import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { label as fmtLabel } from "../lib/format";

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-sky-700 text-white hover:bg-sky-800 disabled:bg-sky-300",
  secondary: "bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  ghost: "text-sky-700 hover:bg-sky-50",
};

export function Button({
  variant = "primary",
  busy,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      disabled={busy || rest.disabled}
      {...rest}
    >
      {busy && <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

function Field({ label, hint, children }: { label?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      {label && <span className="mb-1 block font-medium text-slate-700">{label}</span>}
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const control =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-sky-600 focus:ring-2 focus:ring-sky-100";

export function Input({ label, hint, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <input className={control} {...rest} />
    </Field>
  );
}

export function TextArea({ label, hint, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: string }) {
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
  hint?: string;
  options: { value: string; label: string }[];
}) {
  return (
    <Field label={label} hint={hint}>
      <select className={control} {...rest}>
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
    <label className="flex items-start gap-2 text-sm text-slate-700">
      <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300" {...rest} />
      <span>{label}</span>
    </label>
  );
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-2xl font-bold text-slate-900">{children}</h1>
      {sub && <p className="mt-1 text-sm text-slate-600">{sub}</p>}
    </div>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "success" | "info" | "warning"; children: ReactNode }) {
  if (!children) return null;
  const styles = {
    error: "border-rose-200 bg-rose-50 text-rose-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    info: "border-sky-200 bg-sky-50 text-sky-800",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
  };
  return <div className={`rounded-lg border px-3 py-2 text-sm ${styles[kind]}`}>{children}</div>;
}

export function Spinner({ text = "Loading…" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
      {text}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

const BADGE: Record<string, string> = {
  green: "bg-emerald-100 text-emerald-800",
  amber: "bg-amber-100 text-amber-800",
  red: "bg-rose-100 text-rose-800",
  blue: "bg-sky-100 text-sky-800",
  grey: "bg-slate-100 text-slate-700",
  purple: "bg-violet-100 text-violet-800",
};

export function Badge({ color = "grey", children }: { color?: keyof typeof BADGE; children: ReactNode }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${BADGE[color]}`}>{children}</span>;
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

export function StatusBadge({ status }: { status: string }) {
  return <Badge color={STATUS_COLOR[status] ?? "grey"}>{fmtLabel(status)}</Badge>;
}

export function Stars({ value, count }: { value: number | null; count?: number }) {
  if (value == null) return <span className="text-xs text-slate-500">No ratings yet</span>;
  return (
    <span className="text-sm text-amber-600" title={`${value} out of 5`}>
      {"★".repeat(Math.round(value))}
      <span className="text-slate-300">{"★".repeat(5 - Math.round(value))}</span>
      <span className="ml-1 text-xs text-slate-600">
        {value.toFixed(1)}
        {count != null && ` (${count})`}
      </span>
    </span>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-slate-900">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
