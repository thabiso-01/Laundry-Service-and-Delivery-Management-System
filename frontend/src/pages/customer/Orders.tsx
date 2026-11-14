import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Order, OrderSummary, Page } from "../../api/types";
import { MapView } from "../../components/MapView";
import { AuthImage, EvidenceCards, Money, OrderHeader, Schedule, Timeline } from "../../components/order";
import { Alert, Button, Card, Empty, PageTitle, Select, Spinner, StatusBadge, TextArea } from "../../components/ui";
import { osmLink, rands, when, windowText } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

// UR-013 order history
export function Orders() {
  const { data, error, loading } = useAsync(() => api<Page<OrderSummary>>("/api/orders?limit=50"));
  return (
    <div>
      <PageTitle>My orders</PageTitle>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
        <Empty>No orders yet. <Link to="/search" className="text-sky-700 underline">Find a laundry</Link>.</Empty>
      ) : (
        <div className="space-y-2">
          {data.items.map((o) => (
            <Link key={o.id} to={`/orders/${o.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-4 hover:border-sky-300">
              <div>
                <p className="font-mono font-semibold">{o.order_number}</p>
                <p className="text-sm text-slate-500">{o.business_name} · collection {windowText(o.collection_window_start, o.collection_window_end)}</p>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm">{rands(o.total_cents)}</span>
                <StatusBadge status={o.status} />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

interface Otp { purpose: string; code: string; expires_at: string }
interface Tracking { job_kind: string; driver_first_name: string; latitude: number | null; longitude: number | null; recorded_at: string | null; is_live: boolean; distance_to_destination_km: number | null }

function CodeCard({ order }: { order: Order }) {
  const { data, error, reload } = useAsync(() => api<Otp>(`/api/orders/${order.id}/otp`), [order.id, order.status]);
  const regen = useAction();
  if (error && !data) {
    return (
      <Card title="Your code">
        <p className="mb-2 text-sm text-slate-600">{error}</p>
        <Button variant="secondary" busy={regen.busy} onClick={() => void regen.run(async () => { await api(`/api/orders/${order.id}/otp/regenerate`, { method: "POST" }); await reload(); })}>Generate a new code</Button>
      </Card>
    );
  }
  if (!data) return null;
  return (
    <Card title={data.purpose === "collection" ? "Collection code" : "Delivery code"}>
      <p className="font-mono text-4xl font-bold tracking-[0.3em] text-sky-800">{data.code}</p>
      <p className="mt-2 text-sm text-slate-600">Give this code to the driver <b>only when they are at your door</b> with your bag. Never share it over the phone.</p>
      <p className="mt-1 text-xs text-slate-500">Valid until {when(data.expires_at)}</p>
      <Button variant="ghost" className="mt-2 px-0" busy={regen.busy}
        onClick={() => void regen.run(async () => { await api(`/api/orders/${order.id}/otp/regenerate`, { method: "POST" }); await reload(); })}>
        Make a new code
      </Button>
    </Card>
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
  return (
    <Card title="Your driver">
      <p className="text-sm">
        <b>{order.driver.first_name}</b> is {order.driver.job_kind === "collection" ? "collecting" : "delivering"} your laundry
        {order.driver.vehicle_type && <> · {order.driver.vehicle_type} {order.driver.vehicle_registration}</>}
      </p>
      {order.driver.phone && <p className="text-sm text-slate-600">☎ {order.driver.phone}</p>}
      {t?.latitude != null ? (
        <>
          <p className="mt-2 text-sm">
            {t.is_live ? "📍 Live" : "Last seen"} {t.recorded_at && when(t.recorded_at)}
            {t.distance_to_destination_km != null && ` · ${t.distance_to_destination_km.toFixed(1)} km from the next stop`} ·{" "}
            <a href={osmLink(t.latitude, t.longitude!)} target="_blank" rel="noreferrer" className="text-sky-700 underline">open map</a>
          </p>
          <div className="mt-2">
            <MapView height={240} points={[
              { latitude: t.latitude, longitude: t.longitude!, label: `${t.driver_first_name} (driver)`, color: t.is_live ? "orange" : "grey" },
              { latitude: order.collection_address.latitude, longitude: order.collection_address.longitude, label: "Your address", color: "blue" },
            ]} />
          </div>
        </>
      ) : <p className="mt-2 text-sm text-slate-500">Location will appear once the driver starts moving.</p>}
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
  if (!targets.length) return <Card title="Thanks for your review!"><p className="text-sm text-slate-600">Your feedback helps other customers.</p></Card>;
  return (
    <Card title="Rate your experience">
      <div className="space-y-3">
        <Select label="What are you rating?" value={targets.some((t) => t.value === target) ? target : targets[0].value}
          onChange={(e) => setTarget(e.target.value)} options={targets} />
        <Select label="Rating" value={rating} onChange={(e) => setRating(e.target.value)}
          options={["5", "4", "3", "2", "1"].map((r) => ({ value: r, label: "★".repeat(Number(r)) }))} />
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
    const checkout = await api<{ reference: string; checkout_url: string }>(`/api/orders/${order.id}/pay`, { method: "POST" });
    // Sandbox gateway: complete the payment straight away. A real gateway redirects here.
    await api(checkout.checkout_url, { json: { outcome: "paid" } });
    await reload();
  });

  const canCancel = order.status === "placed" || order.status === "accepted";

  return (
    <div>
      <OrderHeader order={order} />
      {order.declined_reason && <div className="mb-4"><Alert>Declined by the laundry: {order.declined_reason}</Alert></div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          {order.balance_cents > 0 && !["cancelled", "declined"].includes(order.status) && (
            <Card title={order.paid_cents ? "Balance to pay" : "Payment needed"}>
              <p className="mb-3 text-sm text-slate-600">
                {order.paid_cents ? "Your laundry weighed more than estimated." : "The laundry starts once your order is paid."}{" "}
                Amount due: <b>{rands(order.balance_cents)}</b>
              </p>
              <Alert>{paying.error}</Alert>
              <Button busy={paying.busy} onClick={pay}>Pay {rands(order.balance_cents)}</Button>
              <p className="mt-2 text-xs text-slate-500">Test mode: payments go through a sandbox gateway; no real money is taken.</p>
            </Card>
          )}
          {(order.status === "accepted" || order.status === "out_for_delivery") && <CodeCard order={order} />}
          <TrackingCard order={order} />
          <Card title="Progress"><Timeline events={order.history} /></Card>
          <EvidenceCards order={order} />
          {order.status === "delivered" && <ReviewCard order={order} />}
        </div>
        <div className="space-y-4">
          <Card title="Order"><Money order={order} /></Card>
          <Card title="Schedule"><Schedule order={order} /></Card>
          <Card title="Bag label">
            <AuthImage path={`/api/orders/${order.id}/qr`} alt={`QR code for ${order.order_number}`} className="mx-auto h-40 w-40" />
            <p className="mt-2 text-center text-xs text-slate-500">The driver and laundry scan this code to confirm it's your bag.</p>
          </Card>
          <Card>
            <div className="flex flex-wrap gap-2">
              <Link to={`/incidents/new?order=${order.id}`}><Button variant="secondary">Report a problem</Button></Link>
              {canCancel && (
                <Button variant="danger" busy={cancelling.busy} onClick={() => {
                  if (!confirm("Cancel this order?")) return;
                  void cancelling.run(async () => { await api(`/api/orders/${order.id}/cancel`, { json: {} }); await reload(); });
                }}>Cancel order</Button>
              )}
            </div>
            <Alert>{cancelling.error}</Alert>
          </Card>
        </div>
      </div>
    </div>
  );
}
