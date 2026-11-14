import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundryDetail, Order, Quote } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AddressPicker, EMPTY_ADDRESS, type AddressValue } from "../../components/AddressPicker";
import { MapView } from "../../components/MapView";
import { Alert, Button, Card, Empty, PageTitle, Select, Spinner, Stars, TextArea } from "../../components/ui";
import { DEFAULT_LOCATION, UNIT_LABEL, label, rands, slots, when } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

interface ReviewOut { id: string; rating: number; comment: string | null; reviewer: string; created_at: string }

// UR-006 compare services, UR-007 place an order, UR-008 schedule collection & delivery
export function LaundryPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const { me } = useAuth();
  const navigate = useNavigate();
  const lat = Number(params.get("lat") ?? DEFAULT_LOCATION.latitude);
  const lng = Number(params.get("lng") ?? DEFAULT_LOCATION.longitude);

  const laundry = useAsync(() => api<LaundryDetail>(`/api/laundries/${id}?lat=${lat}&lng=${lng}`), [id]);
  const reviews = useAsync(() => api<ReviewOut[]>(`/api/laundries/${id}/reviews`), [id]);

  const [qty, setQty] = useState<Record<string, number>>({});
  // Start from the customer's search location; they refine it on the map
  const [addr, setAddr] = useState<AddressValue>({ ...EMPTY_ADDRESS, latitude: lat, longitude: lng });
  const allSlots = useMemo(() => slots(), []);
  const [collection, setCollection] = useState(allSlots[0]?.start ?? "");
  const [delivery, setDelivery] = useState("");
  const [notes, setNotes] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const quoting = useAction();
  const placing = useAction();

  if (laundry.loading) return <Spinner />;
  if (laundry.error || !laundry.data) return <Alert>{laundry.error ?? "Laundry not found"}</Alert>;
  const l = laundry.data;

  const chosen = l.services.filter((s) => (qty[s.id] ?? 0) > 0);
  const slowest = Math.max(0, ...chosen.map((s) => s.turnaround_hours));
  const collectionSlot = allSlots.find((s) => s.start === collection);
  const deliverySlots = collectionSlot
    ? allSlots.filter((s) => new Date(s.start).getTime() >= new Date(collectionSlot.end).getTime() + slowest * 3600_000)
    : [];
  const deliveryChoice = deliverySlots.some((s) => s.start === delivery) ? delivery : deliverySlots[0]?.start ?? "";

  const body = () => {
    const c = collectionSlot!;
    const d = deliverySlots.find((s) => s.start === deliveryChoice)!;
    return {
      business_id: l.id,
      items: chosen.map((s) => ({ service_id: s.id, quantity: qty[s.id] })),
      collection_address: {
        address_line: addr.address_line, suburb: addr.suburb || null, city: addr.city,
        province: addr.province || null, postal_code: addr.postal_code || null,
        latitude: addr.latitude, longitude: addr.longitude,
      },
      collection_window: { start: c.start, end: c.end },
      delivery_window: { start: d.start, end: d.end },
      notes: notes || null,
    };
  };

  const ready = chosen.length > 0 && collectionSlot && deliveryChoice && addr.address_line && addr.city
    && addr.latitude != null && addr.longitude != null;

  const getQuote = () => void quoting.run(async () => setQuote(await api<Quote>("/api/orders/quote", { json: body() })));
  const place = () =>
    void placing.run(async () => {
      const order = await api<Order>("/api/orders", { json: body() });
      navigate(`/orders/${order.id}`);
    });

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <div className="space-y-4">
        <div>
          <PageTitle sub={[l.address_line, l.suburb, l.city].filter(Boolean).join(", ")}>{l.business_name}</PageTitle>
          <div className="-mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <Stars value={l.rating_avg} count={l.rating_count} />
            {l.distance_km != null && <span>{l.distance_km.toFixed(1)} km away</span>}
            {l.contact_phone && <span>☎ {l.contact_phone}</span>}
          </div>
          {l.description && <p className="mt-3 text-slate-700">{l.description}</p>}
        </div>

        <MapView height={200} zoom={14} points={[{ latitude: l.latitude, longitude: l.longitude, label: l.business_name, color: "green" }]} />

        <Card title="Services">
          <ul className="divide-y divide-slate-100">
            {l.services.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900">{s.name}</p>
                  <p className="text-xs text-slate-500">
                    {label(s.category)} · ready in {s.turnaround_hours} h
                    {s.min_quantity > 1 && ` · minimum ${s.min_quantity} ${UNIT_LABEL[s.pricing_unit]}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-700">{s.price_display}</span>
                  {me?.role === "customer" && (
                    <input type="number" min={0} max={100} aria-label={`Quantity of ${s.name}`}
                      className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-sm"
                      value={qty[s.id] ?? 0}
                      onChange={(e) => { setQuote(null); setQty({ ...qty, [s.id]: Math.max(0, Number(e.target.value)) }); }} />
                  )}
                </div>
              </li>
            ))}
          </ul>
          {chosen.some((s) => s.pricing_unit === "per_kg") && (
            <p className="mt-2 text-xs text-slate-500">Per-kg prices are estimates: the laundry weighs your load and you pay or are refunded the difference.</p>
          )}
        </Card>

        <Card title="Reviews">
          {reviews.data?.length ? (
            <ul className="space-y-3">
              {reviews.data.map((r) => (
                <li key={r.id} className="text-sm">
                  <Stars value={r.rating} /> <span className="text-slate-500">— {r.reviewer}, {when(r.created_at)}</span>
                  {r.comment && <p className="mt-1 text-slate-700">{r.comment}</p>}
                </li>
              ))}
            </ul>
          ) : <Empty>No reviews yet.</Empty>}
        </Card>
      </div>

      <aside>
        <Card title="Book a collection" className="lg:sticky lg:top-20">
          {!me ? (
            <p className="text-sm text-slate-600"><Link to="/login" className="text-sky-700 underline">Log in</Link> or{" "}
              <Link to="/register" className="text-sky-700 underline">create an account</Link> to order.</p>
          ) : me.role !== "customer" ? (
            <p className="text-sm text-slate-600">Only customer accounts can place orders.</p>
          ) : (
            <div className="space-y-3">
              {chosen.length === 0 && <Alert kind="info">Choose how much of each service you need.</Alert>}
              <AddressPicker label="Collection address" required value={addr}
                onChange={(next) => { setQuote(null); setAddr(next); }} />
              <Select label="Collection time" value={collection}
                onChange={(e) => { setQuote(null); setCollection(e.target.value); }}
                options={allSlots.map((s) => ({ value: s.start, label: s.label }))} />
              <Select label="Delivery time" value={deliveryChoice} disabled={!deliverySlots.length}
                onChange={(e) => { setQuote(null); setDelivery(e.target.value); }}
                hint={slowest ? `Earliest is ${slowest} h after collection (slowest service).` : undefined}
                options={deliverySlots.length ? deliverySlots.map((s) => ({ value: s.start, label: s.label }))
                  : [{ value: "", label: "Choose services first" }]} />
              <TextArea label="Notes for the driver" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Gate code, where to wait…" />
              <Alert>{quoting.error || placing.error}</Alert>
              {quote && (
                <div className="rounded-lg bg-slate-50 p-3 text-sm">
                  {quote.items.map((i) => (
                    <div key={i.service_id} className="flex justify-between"><span>{i.service_name} <span className="text-slate-500">({i.description})</span></span><span>{rands(i.line_total_cents)}</span></div>
                  ))}
                  <div className="flex justify-between text-slate-600"><span>Collection & delivery ({quote.distance_km.toFixed(1)} km)</span><span>{rands(quote.delivery_fee_cents)}</span></div>
                  <div className="mt-1 flex justify-between border-t border-slate-200 pt-1 font-semibold"><span>Total</span><span>{quote.total_display}</span></div>
                </div>
              )}
              {quote ? (
                <Button className="w-full" busy={placing.busy} onClick={place}>Place order</Button>
              ) : (
                <Button className="w-full" busy={quoting.busy} disabled={!ready} onClick={getQuote}>See price</Button>
              )}
            </div>
          )}
        </Card>
      </aside>
    </div>
  );
}
