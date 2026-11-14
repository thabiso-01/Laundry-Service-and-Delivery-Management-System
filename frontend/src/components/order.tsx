// Pieces of the order page shared by customers, laundries and admins.

import { useEffect, useState } from "react";
import { apiBlobUrl } from "../api/client";
import type { Handover, Order, Seal, StatusEvent } from "../api/types";
import { label, rands, when, windowText } from "../lib/format";
import { Badge, Card, KeyValue, StatusBadge } from "./ui";

export function Timeline({ events }: { events: StatusEvent[] }) {
  return (
    <ol className="space-y-3 border-l-2 border-slate-200 pl-4">
      {events.map((e, i) => (
        <li key={i} className="relative text-sm">
          <span className="absolute -left-[1.4rem] top-1 h-3 w-3 rounded-full border-2 border-white bg-sky-600" />
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={e.to_status} />
            <span className="text-slate-500">{when(e.created_at)}</span>
          </div>
          {(e.actor_name || e.note) && (
            <p className="mt-0.5 text-slate-600">
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

const HANDOVER_TEXT: Record<string, string> = {
  customer_to_driver: "Collected from customer",
  driver_to_business: "Received by laundry",
  business_to_driver: "Handed to delivery driver",
  driver_to_customer: "Delivered to customer",
};

export function Handovers({ items }: { items: Handover[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">No handovers yet.</p>;
  return (
    <ul className="space-y-2 text-sm">
      {items.map((h, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2">
          <span className="font-medium">✔ {HANDOVER_TEXT[h.kind] ?? label(h.kind)}</span>
          <Badge color="blue">{h.method === "otp" ? "one-time code" : "QR scan"}</Badge>
          {h.location_flagged && <Badge color="red">location flagged</Badge>}
          <span className="text-slate-500">{when(h.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

export function Seals({ items }: { items: Seal[] }) {
  if (!items.length) return <p className="text-sm text-slate-500">No seals recorded yet.</p>;
  return (
    <ul className="flex flex-wrap gap-2 text-sm">
      {items.map((s) => (
        <li key={s.seal_number} className="rounded-lg border border-slate-200 px-2 py-1">
          <span className="font-mono">{s.seal_number}</span>{" "}
          <span className="text-xs text-slate-500">{s.leg}</span>{" "}
          {s.check_result && <Badge color={s.check_result === "intact" ? "green" : "red"}>{label(s.check_result)}</Badge>}
        </li>
      ))}
    </ul>
  );
}

export function Money({ order }: { order: Order }) {
  return (
    <div className="space-y-1 text-sm">
      {order.items.map((i) => (
        <div key={i.service_id} className="flex justify-between gap-2">
          <span>{i.service_name} <span className="text-slate-500">({i.description})</span></span>
          <span>{rands(i.line_total_cents)}</span>
        </div>
      ))}
      <div className="flex justify-between text-slate-600"><span>Collection & delivery</span><span>{rands(order.delivery_fee_cents)}</span></div>
      {order.adjustment_cents !== 0 && (
        <div className="flex justify-between text-slate-600"><span>After weighing</span><span>{rands(order.adjustment_cents)}</span></div>
      )}
      <div className="flex justify-between border-t border-slate-200 pt-1 font-semibold">
        <span>Total{order.is_estimate && " (estimate)"}</span><span>{rands(order.final_total_cents)}</span>
      </div>
      <div className="flex justify-between text-slate-600"><span>Paid</span><span>{rands(order.paid_cents)}</span></div>
      {order.balance_cents > 0 && <div className="flex justify-between font-semibold text-rose-700"><span>Still to pay</span><span>{rands(order.balance_cents)}</span></div>}
      {order.balance_cents < 0 && <div className="flex justify-between font-semibold text-emerald-700"><span>Refund due</span><span>{rands(-order.balance_cents)}</span></div>}
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
  return src ? <img src={src} alt={alt} className={className} /> : <div className={`bg-slate-100 ${className}`} />;
}

export function OrderHeader({ order }: { order: Order }) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <h1 className="font-mono text-2xl font-bold text-slate-900">{order.order_number}</h1>
      <StatusBadge status={order.status} />
      <span className="text-sm text-slate-500">{order.business_name} · placed {when(order.created_at)}</span>
    </div>
  );
}

export function EvidenceCards({ order }: { order: Order }) {
  return (
    <>
      <Card title="Handovers"><Handovers items={order.handovers} /></Card>
      <Card title="Tamper-evident seals"><Seals items={order.seals} /></Card>
    </>
  );
}
