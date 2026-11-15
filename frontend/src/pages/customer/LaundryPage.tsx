import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundryDetail, Order, Quote } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AddressPicker, EMPTY_ADDRESS, type AddressValue } from "../../components/AddressPicker";
import { MapView } from "../../components/MapView";
import { Icon } from "../../components/icons";
import { Alert, Button, ButtonLink, Card, Empty, PageTitle, Select, Spinner, Stars, TextArea } from "../../components/ui";
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

  const setQuantity = (sid: string, n: number) => { setQuote(null); setQty({ ...qty, [sid]: Math.max(0, Math.min(100, n || 0)) }); };
  const isCustomer = me?.role === "customer";

  return (
    <div>
      <PageTitle back={{ to: `/search?lat=${lat}&lng=${lng}`, label: "All laundries" }}
        sub={
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="inline-flex items-center gap-1"><Icon name="pin" className="h-4 w-4" />{[l.address_line, l.suburb, l.city].filter(Boolean).join(", ")}</span>
            <Stars value={l.rating_avg} count={l.rating_count} />
            {l.distance_km != null && <span>{l.distance_km.toFixed(1)} km away</span>}
            {l.contact_phone && <a href={`tel:${l.contact_phone}`} className="inline-flex items-center gap-1 hover:text-slate-800"><Icon name="phone" className="h-4 w-4" />{l.contact_phone}</a>}
          </div>
        }>
        {l.business_name}
      </PageTitle>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-5">
          {l.description && <p className="text-slate-700">{l.description}</p>}

          <div className="overflow-hidden rounded-xl border border-slate-200 shadow-card">
            <MapView height={200} zoom={14} points={[{ latitude: l.latitude, longitude: l.longitude, label: l.business_name, color: "green" }]} />
          </div>

          <Card title={isCustomer ? "1. Choose your services" : "Services & prices"}
            description={isCustomer ? "Set how much of each you need. Per-kg amounts are an estimate." : undefined} padded={false}>
            <ul className="divide-y divide-slate-100">
              {l.services.map((s) => {
                const n = qty[s.id] ?? 0;
                return (
                  <li key={s.id} className={`flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5 ${n > 0 ? "bg-brand-50/40" : ""}`}>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900">{s.name}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                        <span>{label(s.category)}</span><span>·</span>
                        <span className="inline-flex items-center gap-1"><Icon name="clock" className="h-3 w-3" />ready in {s.turnaround_hours} h</span>
                        {s.min_quantity > 1 && <><span>·</span><span>minimum {s.min_quantity} {UNIT_LABEL[s.pricing_unit]}</span></>}
                      </p>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-sm font-semibold text-slate-900">{s.price_display}</span>
                      {isCustomer && (
                        <div className="flex items-center rounded-lg shadow-sm ring-1 ring-slate-300 ring-inset">
                          <button type="button" aria-label={`Less ${s.name}`} disabled={n === 0} onClick={() => setQuantity(s.id, n - 1)}
                            className="grid h-9 w-9 place-items-center rounded-l-lg text-lg text-slate-600 hover:bg-slate-50 disabled:text-slate-300">−</button>
                          <input type="number" min={0} max={100} aria-label={`Quantity of ${s.name}`} value={n}
                            onChange={(e) => setQuantity(s.id, Number(e.target.value))}
                            className="h-9 w-12 border-x border-slate-200 text-center text-sm font-medium tabular-nums outline-none [appearance:textfield] focus:bg-brand-50 [&::-webkit-inner-spin-button]:appearance-none" />
                          <button type="button" aria-label={`More ${s.name}`} onClick={() => setQuantity(s.id, n + 1)}
                            className="grid h-9 w-9 place-items-center rounded-r-lg text-lg text-slate-600 hover:bg-slate-50">+</button>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            {chosen.some((s) => s.pricing_unit === "per_kg") && (
              <p className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500 sm:px-5">
                Per-kg prices are estimates: the laundry weighs your load and you pay or are refunded the difference.
              </p>
            )}
          </Card>

          <Card title="Reviews">
            {reviews.data?.length ? (
              <ul className="divide-y divide-slate-100">
                {reviews.data.map((r) => (
                  <li key={r.id} className="py-3 text-sm first:pt-0 last:pb-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Stars value={r.rating} /> <span className="text-slate-500">{r.reviewer} · {when(r.created_at)}</span>
                    </div>
                    {r.comment && <p className="mt-1 text-slate-700">{r.comment}</p>}
                  </li>
                ))}
              </ul>
            ) : <Empty icon="star">No reviews yet.</Empty>}
          </Card>
        </div>

        <aside>
          <div className="lg:sticky lg:top-24">
            <Card title={isCustomer ? "2. Book a collection" : "Book a collection"}>
              {!me ? (
                <div className="space-y-3 text-center">
                  <p className="text-sm text-slate-600">Log in or create a free account to order from {l.business_name}.</p>
                  <ButtonLink to="/login" className="w-full">Log in to order</ButtonLink>
                  <ButtonLink to="/register" variant="secondary" className="w-full">Create an account</ButtonLink>
                </div>
              ) : !isCustomer ? (
                <p className="text-sm text-slate-600">Only customer accounts can place orders.</p>
              ) : (
                <div className="space-y-4">
                  {chosen.length === 0 && <Alert kind="info">Start by choosing how much of each service you need.</Alert>}
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
                    <div className="space-y-1.5 rounded-lg bg-slate-50 p-4 text-sm ring-1 ring-slate-200 ring-inset">
                      {quote.items.map((i) => (
                        <div key={i.service_id} className="flex justify-between gap-2"><span>{i.service_name} <span className="text-slate-500">({i.description})</span></span><span className="tabular-nums">{rands(i.line_total_cents)}</span></div>
                      ))}
                      <div className="flex justify-between gap-2 text-slate-600"><span>Collection & delivery ({quote.distance_km.toFixed(1)} km)</span><span className="tabular-nums">{rands(quote.delivery_fee_cents)}</span></div>
                      <div className="mt-2 flex justify-between border-t border-slate-200 pt-2 text-base font-semibold"><span>Total</span><span className="tabular-nums">{quote.total_display}</span></div>
                    </div>
                  )}
                  {quote ? (
                    <Button size="lg" className="w-full" busy={placing.busy} onClick={place}>Place order</Button>
                  ) : (
                    <Button size="lg" variant={ready ? "primary" : "secondary"} className="w-full" busy={quoting.busy} disabled={!ready} onClick={getQuote}>See price</Button>
                  )}
                  {quote && <p className="text-center text-xs text-slate-500">You'll pay on the next screen.</p>}
                </div>
              )}
            </Card>
          </div>
        </aside>
      </div>
    </div>
  );
}
