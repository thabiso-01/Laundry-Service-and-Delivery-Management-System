import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Order, OrderSummary, Page } from "../../api/types";
import { Icon } from "../../components/icons";
import { MapView } from "../../components/MapView";
import { AuthImage, EvidenceCards, Money, OrderHeader, OrderProgress, Schedule, Timeline } from "../../components/order";
import { Alert, Button, ButtonLink, Card, Empty, ListRow, PageTitle, Select, Spinner, StatusBadge, TextArea } from "../../components/ui";
import { label, osmLink, rands, when, windowText } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

// UR-013 order history
export function Orders() {
  const { data, error, loading } = useAsync(() => api<Page<OrderSummary>>("/api/orders?limit=50"));
  return (
    <div>
      <PageTitle sub="Track current orders and see past ones." actions={<ButtonLink to="/search" icon="plus">New order</ButtonLink>}>My orders</PageTitle>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
        <Card>
          <Empty icon="package" title="No orders yet" action={<ButtonLink to="/search" icon="search">Find a laundry</ButtonLink>}>
            Choose a laundry near you, pick a collection time, and we'll do the rest.
          </Empty>
        </Card>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-slate-100">
            {data.items.map((o) => (
              <li key={o.id}>
                <ListRow to={`/orders/${o.id}`}>
                  <div className="min-w-0">
                    <p className="font-mono text-sm font-semibold text-slate-900">{o.order_number}</p>
                    <p className="truncate text-sm text-slate-500">{o.business_name} · collection {windowText(o.collection_window_start, o.collection_window_end)}</p>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-sm font-medium tabular-nums text-slate-700">{rands(o.total_cents)}</span>
                    <StatusBadge status={o.status} />
                  </div>
                </ListRow>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

interface Otp { purpose: string; code: string; expires_at: string }
interface Tracking { job_kind: string; driver_first_name: string; latitude: number | null; longitude: number | null; recorded_at: string | null; is_live: boolean; distance_to_destination_km: number | null }

function CodeCard({ order }: { order: Order }) {
  const { data, error, reload } = useAsync(() => api<Otp>(`/api/orders/${order.id}/otp`), [order.id, order.status]);
  const regen = useAction();
  const regenerate = () => void regen.run(async () => { await api(`/api/orders/${order.id}/otp/regenerate`, { method: "POST" }); await reload(); });
  if (error && !data) {
    return (
      <Card title="Your code">
        <p className="mb-3 text-sm text-slate-600">{error}</p>
        <Button variant="secondary" icon="refresh" busy={regen.busy} onClick={regenerate}>Generate a new code</Button>
      </Card>
    );
  }
  if (!data) return null;
  return (
    <section className="overflow-hidden rounded-xl border border-brand-200 bg-surface shadow-card">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4 bg-brand-50/60 p-5">
        <div className="min-w-0 flex-1 basis-60">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-slate-900">
            <Icon name="key" className="h-4 w-4 text-brand-700" />
            {data.purpose === "collection" ? "Collection code" : "Delivery code"}
          </h2>
          <p className="mt-1 text-sm text-slate-600">
            Give this code to the driver <b>only when they are at your door</b> with your bag. Never share it over the phone.
          </p>
        </div>
        <div className="rounded-xl bg-surface px-5 py-3 text-center shadow-sm ring-1 ring-brand-100">
          <p className="font-mono text-4xl font-bold tracking-[0.25em] text-brand-800">{data.code}</p>
          <p className="mt-1 text-xs text-slate-500">Valid until {when(data.expires_at)}</p>
        </div>
      </div>
      <div className="flex justify-end border-t border-brand-100 px-3 py-2">
        <Button variant="ghost" size="sm" icon="refresh" busy={regen.busy} onClick={regenerate}>Make a new code</Button>
      </div>
    </section>
  );
}

function TrackingCard({ order }: { order: Order }) {
  const [t, setT] = useState<Tracking | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api<Tracking>(`/api/orders/${order.id}/tracking`).then((r) => alive && setT(r)).catch(() => alive && setT(null));
    void load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [order.id]);
  if (!order.driver) return null;
  const d = order.driver;
  return (
    <Card title="Your driver" actions={d.phone && (
      <a href={`tel:${d.phone}`} className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline">
        <Icon name="phone" className="h-4 w-4" /> Call {d.first_name}
      </a>
    )}>
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700"><Icon name="truck" /></span>
        <div className="text-sm">
          <p><b>{d.first_name}</b> is {d.job_kind === "collection" ? "collecting" : "delivering"} your laundry</p>
          {d.vehicle_type && <p className="text-slate-500">{label(d.vehicle_type)} · {d.vehicle_registration}</p>}
        </div>
      </div>
      {t?.latitude != null ? (
        <>
          <p className="mt-4 flex flex-wrap items-center gap-x-1.5 text-sm text-slate-600">
            {t.is_live
              ? <span className="inline-flex items-center gap-1.5 font-medium text-emerald-700"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />Live</span>
              : <span>Last seen</span>}
            {t.recorded_at && <span>{when(t.recorded_at)}</span>}
            {t.distance_to_destination_km != null && <span>· {t.distance_to_destination_km.toFixed(1)} km from the next stop</span>}
            <span>·</span>
            <a href={osmLink(t.latitude, t.longitude!)} target="_blank" rel="noreferrer" className="text-brand-700 underline">open map</a>
          </p>
          <div className="mt-3 overflow-hidden rounded-lg">
            <MapView height={240} points={[
              { latitude: t.latitude, longitude: t.longitude!, label: `${t.driver_first_name} (driver)`, color: t.is_live ? "orange" : "grey" },
              { latitude: order.collection_address.latitude, longitude: order.collection_address.longitude, label: "Your address", color: "blue" },
            ]} />
          </div>
        </>
      ) : <p className="mt-4 text-sm text-slate-500">The map appears once the driver starts moving.</p>}
    </Card>
  );
}

function ReviewCard({ order }: { order: Order }) {
  const jobs = order.trips.filter((t) => t.driver_first_name && t.status === "completed");
  const [rating, setRating] = useState("5");
  const [comment, setComment] = useState("");
  const [target, setTarget] = useState("business");
  const [done, setDone] = useState<string[]>([]);
  const { busy, error, run } = useAction();
  const targets = [{ value: "business", label: `The laundry (${order.business_name})` },
    ...jobs.map((j) => ({ value: j.job_id, label: `${j.driver_first_name} (${j.kind} driver)` }))]
    .filter((t) => !done.includes(t.value));
  if (!targets.length) {
    return <Alert kind="success" title="Thanks for your review!">Your feedback helps other customers choose.</Alert>;
  }
  return (
    <Card title="Rate your experience" description="How did it go? Your review helps other customers.">
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="What are you rating?" value={targets.some((t) => t.value === target) ? target : targets[0].value}
            onChange={(e) => setTarget(e.target.value)} options={targets} />
          <Select label="Rating" value={rating} onChange={(e) => setRating(e.target.value)}
            options={["5", "4", "3", "2", "1"].map((r) => ({ value: r, label: `${"★".repeat(Number(r))}  ${r} out of 5` }))} />
        </div>
        <TextArea label="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
        <Alert>{error}</Alert>
        <Button busy={busy} onClick={() => void run(async () => {
          const t = targets.some((x) => x.value === target) ? target : targets[0].value;
          await api(`/api/orders/${order.id}/reviews`, { json: t === "business"
            ? { target: "business", rating: Number(rating), comment: comment || null }
            : { target: "driver", job_id: t, rating: Number(rating), comment: comment || null } });
          setDone([...done, t]); setComment("");
        })}>Submit review</Button>
      </div>
    </Card>
  );
}

// UR-012 tracking, payments, codes, reviews
export function OrderDetail() {
  const { id } = useParams();
  const { data: order, error, loading, reload } = useAsync(() => api<Order>(`/api/orders/${id}`), [id]);
  const paying = useAction();
  const cancelling = useAction();

  useEffect(() => {
    const timer = setInterval(() => void reload(), 30000); // pick up status changes
    return () => clearInterval(timer);
  }, [reload]);

  if (loading && !order) return <Spinner />;
  if (error || !order) return <Alert>{error}</Alert>;

  const pay = () => void paying.run(async () => {
    const checkout = await api<{ provider: string; checkout_url: string; form_action: string | null;
      form_fields: [string, string][] | null }>(`/api/orders/${order.id}/pay`, { method: "POST" });
    if (checkout.form_action && checkout.form_fields) {
      // Real gateway (PayFast): post the signed form; the customer pays on PayFast's
      // page and comes back to this order page afterwards
      const form = document.createElement("form");
      form.method = "POST";
      form.action = checkout.form_action;
      for (const [name, value] of checkout.form_fields) {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.appendChild(input);
      }
      document.body.appendChild(form);
      form.submit();
      return;
    }
    // Sandbox gateway: complete the payment straight away
    await api(checkout.checkout_url, { json: { outcome: "paid" } });
    await reload();
  });
  const returned = new URLSearchParams(window.location.search).get("payment");
  const canCancel = order.status === "placed" || order.status === "accepted";
  const mustPay = order.balance_cents > 0 && !["cancelled", "declined"].includes(order.status);

  return (
    <div>
      <OrderHeader order={order} back={{ to: "/orders", label: "My orders" }} />
      <div className="mb-5 space-y-3 empty:hidden">
        {order.declined_reason && <Alert title="Declined by the laundry">{order.declined_reason}</Alert>}
        {returned === "return" && order.balance_cents > 0 && (
          <Alert kind="info">Thanks! We're waiting for PayFast to confirm your payment. This page updates by itself.</Alert>
        )}
        {returned === "cancelled" && order.balance_cents > 0 && (
          <Alert kind="warning">Payment was cancelled. You can try again below.</Alert>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <OrderProgress order={order} />

          {mustPay && (
            <section className="rounded-xl border border-amber-200 bg-amber-50/70 p-5 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-amber-100 text-amber-700"><Icon name="card" /></span>
                  <div>
                    <h2 className="text-[15px] font-semibold text-slate-900">{order.paid_cents ? "Balance to pay" : "Payment needed"}</h2>
                    <p className="text-sm text-slate-600">
                      {order.paid_cents ? "Your laundry weighed more than estimated." : "The laundry starts once your order is paid."}
                    </p>
                  </div>
                </div>
                <Button size="lg" busy={paying.busy} onClick={pay}>Pay {rands(order.balance_cents)}</Button>
              </div>
              {paying.error && <div className="mt-3"><Alert>{paying.error}</Alert></div>}
              <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
                <Icon name="lock" className="h-3.5 w-3.5" /> Payments are processed securely; we never see your card details.
              </p>
            </section>
          )}

          {(order.status === "accepted" || order.status === "out_for_delivery") && <CodeCard order={order} />}
          <TrackingCard order={order} />
          {order.status === "delivered" && <ReviewCard order={order} />}
          <EvidenceCards order={order} />
          <Card title="Activity"><Timeline events={order.history} /></Card>
        </div>

        <div className="space-y-5">
          <Card title="Summary"><Money order={order} /></Card>
          <Card title="Collection & delivery"><Schedule order={order} /></Card>
          <Card title="Bag label" description="The driver and laundry scan this to confirm it's your bag.">
            <AuthImage path={`/api/orders/${order.id}/qr`} alt={`QR code for ${order.order_number}`} className="mx-auto h-40 w-40" />
          </Card>
          <Card title="Need help?">
            <div className="flex flex-wrap gap-2">
              <ButtonLink to={`/incidents/new?order=${order.id}`} variant="secondary" icon="flag">Report a problem</ButtonLink>
              {canCancel && (
                <Button variant="ghost" className="text-rose-700 hover:bg-rose-50" busy={cancelling.busy} onClick={() => {
                  if (!confirm("Cancel this order?")) return;
                  void cancelling.run(async () => { await api(`/api/orders/${order.id}/cancel`, { json: {} }); await reload(); });
                }}>Cancel order</Button>
              )}
            </div>
            {cancelling.error && <div className="mt-3"><Alert>{cancelling.error}</Alert></div>}
          </Card>
        </div>
      </div>
    </div>
  );
}
