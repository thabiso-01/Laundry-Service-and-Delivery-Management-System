// Pieces of the order page shared by customers, laundries and admins.

import { useEffect, useState, type ReactNode } from "react";
import { apiBlobUrl } from "../api/client";
import type { Handover, Order, OrderStatus, Seal, StatusEvent } from "../api/types";
import { label, rands, when, windowText } from "../lib/format";
import { Icon } from "./icons";
import { Badge, Card, KeyValue, PageTitle, StatusBadge, statusText } from "./ui";

// ---------- Progress tracker ----------

const clock = (iso: string) =>
  new Intl.DateTimeFormat("en-ZA", { timeZone: "Africa/Johannesburg", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

const STEPS: { status: OrderStatus; title: string }[] = [
  { status: "placed", title: "Placed" },
  { status: "accepted", title: "Accepted" },
  { status: "collected", title: "Collected" },
  { status: "received", title: "At laundry" },
  { status: "processing", title: "Cleaning" },
  { status: "ready", title: "Ready" },
  { status: "out_for_delivery", title: "On the way" },
  { status: "delivered", title: "Delivered" },
];

// One line explaining where the order is, for whoever is looking
const EXPLAIN: Record<string, string> = {
  placed: "Waiting for payment and for the laundry to accept the order.",
  accepted: "A driver will come to collect your bag in the collection window.",
  collected: "The driver has your bag and is taking it to the laundry.",
  received: "The laundry has checked in your bag.",
  processing: "Your laundry is being cleaned.",
  ready: "Clean and packed. A driver will pick it up for delivery.",
  out_for_delivery: "Your laundry is on its way back to you.",
  delivered: "Delivered. Thanks for using LaundryConnect!",
  cancelled: "This order was cancelled.",
  declined: "The laundry couldn't take this order.",
};

export function OrderProgress({ order, explain = true }: { order: Order; explain?: boolean }) {
  const current = STEPS.findIndex((s) => s.status === order.status);
  const stopped = current === -1; // cancelled or declined
  const at = (status: OrderStatus) => order.history.find((e) => e.to_status === status)?.created_at;

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Status</p>
          <p className="text-lg font-semibold text-slate-900">{statusText(order.status)}</p>
        </div>
        {!stopped && <p className="text-sm text-slate-500">Step {current + 1} of {STEPS.length}</p>}
      </div>
      {explain && EXPLAIN[order.status] && (
        <p className="mt-1 text-sm text-slate-600">
          {order.status === "placed" && order.balance_cents <= 0 ? "Paid. Waiting for the laundry to accept your order." : EXPLAIN[order.status]}
        </p>
      )}

      {!stopped && (
        <>
          {/* Bar on phones */}
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100 sm:hidden">
            <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${((current + 1) / STEPS.length) * 100}%` }} />
          </div>
          {/* Steps on bigger screens */}
          <ol className="mt-5 hidden grid-cols-8 sm:grid">
            {STEPS.map((s, i) => {
              const done = i < current || order.status === "delivered";
              const now = i === current && order.status !== "delivered";
              const time = at(s.status);
              return (
                <li key={s.status} className="relative flex flex-col items-center text-center">
                  {i > 0 && <span className={`absolute right-1/2 top-3.5 h-0.5 w-full -translate-y-1/2 ${i <= current ? "bg-brand-600" : "bg-slate-200"}`} />}
                  <span className={`relative z-[1] grid h-7 w-7 place-items-center rounded-full text-xs font-semibold ring-4 ring-white ${
                    done ? "bg-brand-600 text-white" : now ? "bg-white text-brand-700 ring-brand-100 outline-2 outline-brand-600" : "bg-slate-100 text-slate-400"}`}>
                    {done ? <Icon name="check" className="h-3.5 w-3.5" /> : i + 1}
                  </span>
                  <span className={`mt-2 text-xs font-medium ${done || now ? "text-slate-900" : "text-slate-400"}`}>{s.title}</span>
                  {time && <span className="mt-0.5 hidden text-[11px] tabular-nums text-slate-400 md:block" title={when(time)}>{clock(time)}</span>}
                </li>
              );
            })}
          </ol>
        </>
      )}
    </Card>
  );
}

// ---------- Activity history ----------

export function Timeline({ events }: { events: StatusEvent[] }) {
  return (
    <ol className="relative space-y-4 before:absolute before:inset-y-1 before:left-[5px] before:w-px before:bg-slate-200">
      {[...events].reverse().map((e, i) => (
        <li key={i} className="relative pl-6 text-sm">
          <span className={`absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full ring-4 ring-white ${i === 0 ? "bg-brand-600" : "bg-slate-300"}`} />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium text-slate-900">{statusText(e.to_status)}</span>
            <span className="text-slate-400">·</span>
            <span className="text-slate-500">{when(e.created_at)}</span>
          </div>
          {(e.actor_name || e.note) && (
            <p className="mt-0.5 text-slate-500">
              {e.actor_name && <>by {e.actor_name}{e.actor_role && ` (${e.actor_role})`}</>}
              {e.actor_name && e.note && " — "}
              {e.note}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

// ---------- Security checks (handovers + seals) ----------

const HANDOVER_TEXT: Record<string, string> = {
  customer_to_driver: "Collected from customer",
  driver_to_business: "Received by laundry",
  business_to_driver: "Handed to delivery driver",
  driver_to_customer: "Delivered to customer",
};

export function Handovers({ items }: { items: Handover[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">Nothing yet. Each time the bag changes hands it's confirmed here.</p>;
  return (
    <ul className="space-y-3 text-sm">
      {items.map((h, i) => (
        <li key={i} className="flex items-start gap-3">
          <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-50 text-emerald-600">
            <Icon name="check" className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-medium text-slate-900">{HANDOVER_TEXT[h.kind] ?? label(h.kind)}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-slate-500">
              <span>{h.method === "otp" ? "Confirmed with one-time code" : "Confirmed by QR scan"}</span>
              <span>·</span>
              <span>{when(h.created_at)}</span>
              {h.location_flagged && <Badge color="red">location flagged</Badge>}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Seals({ items }: { items: Seal[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">The driver seals your bag at collection; the seal numbers appear here.</p>;
  return (
    <ul className="flex flex-wrap gap-2 text-sm">
      {items.map((s) => (
        <li key={s.seal_number} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 py-1 pl-2.5 pr-1.5">
          <Icon name="seal" className="h-3.5 w-3.5 text-slate-400" />
          <span className="font-mono text-xs font-medium">{s.seal_number}</span>
          <span className="text-xs text-slate-500">{s.leg}</span>
          {s.check_result && <Badge color={s.check_result === "intact" ? "green" : "red"}>{label(s.check_result)}</Badge>}
        </li>
      ))}
    </ul>
  );
}

export function EvidenceCards({ order }: { order: Order }) {
  return (
    <Card title="Security checks" description="Every handover is verified, and the bag is sealed so nobody can open it on the way.">
      <div className="space-y-5">
        <div>
          <h3 className="mb-3 text-xs font-semibold tracking-wide text-slate-500 uppercase">Handovers</h3>
          <Handovers items={order.handovers} />
        </div>
        <div className="border-t border-slate-100 pt-4">
          <h3 className="mb-3 text-xs font-semibold tracking-wide text-slate-500 uppercase">Tamper-evident seals</h3>
          <Seals items={order.seals} />
        </div>
      </div>
    </Card>
  );
}

// ---------- Money and schedule ----------

function Line({ left, right, className = "" }: { left: ReactNode; right: ReactNode; className?: string }) {
  return <div className={`flex justify-between gap-3 ${className}`}><span>{left}</span><span className="tabular-nums">{right}</span></div>;
}

export function Money({ order }: { order: Order }) {
  return (
    <div className="space-y-2 text-sm">
      {order.items.map((i) => (
        <Line key={i.service_id} left={<>{i.service_name} <span className="text-slate-500">({i.description})</span></>} right={rands(i.line_total_cents)} />
      ))}
      <Line className="text-slate-600" left="Collection & delivery" right={rands(order.delivery_fee_cents)} />
      {order.adjustment_cents !== 0 && <Line className="text-slate-600" left="After weighing" right={rands(order.adjustment_cents)} />}
      <Line className="border-t border-slate-200 pt-2 text-base font-semibold text-slate-900"
        left={<>Total{order.is_estimate && <span className="ml-1 text-xs font-normal text-slate-500">(estimate)</span>}</>} right={rands(order.final_total_cents)} />
      <Line className="text-slate-600" left="Paid" right={rands(order.paid_cents)} />
      {order.balance_cents > 0 && <Line className="font-semibold text-rose-700" left="Still to pay" right={rands(order.balance_cents)} />}
      {order.balance_cents < 0 && <Line className="font-semibold text-emerald-700" left="Refund due" right={rands(-order.balance_cents)} />}
    </div>
  );
}

export function Schedule({ order }: { order: Order }) {
  const a = order.collection_address;
  return (
    <KeyValue items={[
      ["Collection", windowText(order.collection_window_start, order.collection_window_end)],
      ["Delivery", windowText(order.delivery_window_start, order.delivery_window_end)],
      ["Address", [a.address_line, a.suburb, a.city].filter(Boolean).join(", ")],
      ["Notes", order.notes],
    ]} />
  );
}

// An image that needs the login token (QR labels, photos)
export function AuthImage({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    apiBlobUrl(path).then((u) => { url = u; setSrc(u); }).catch(() => setSrc(null));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [path]);
  return src ? <img src={src} alt={alt} className={className} /> : <div className={`animate-pulse rounded-lg bg-slate-100 ${className}`} />;
}

export function OrderHeader({ order, back }: { order: Order; back?: { to: string; label: string } }) {
  return (
    <PageTitle back={back} sub={<>{order.business_name} · placed {when(order.created_at)}</>}
      actions={<StatusBadge status={order.status} />}>
      <span className="font-mono">{order.order_number}</span>
    </PageTitle>
  );
}
