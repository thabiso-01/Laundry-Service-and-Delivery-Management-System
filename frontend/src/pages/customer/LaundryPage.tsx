import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundryDetail, Order, Quote } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AddressPicker, EMPTY_ADDRESS, type AddressValue } from "../../components/AddressPicker";
import { MapView } from "../../components/MapView";
import { Icon } from "../../components/icons";
import { CATEGORY_INFO } from "../../lib/categories";
import { Alert, Button, ButtonLink, Card, CoverImage, Empty, Select, Spinner, Stars, TextArea } from "../../components/ui";
import { DEFAULT_LOCATION, UNIT_LABEL, rands, slots, when } from "../../lib/format";
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

  // What's still missing before we can show a price (shown under the button)
  const missing = [
    chosen.length === 0 && "choose at least one service",
    (addr.latitude == null || addr.longitude == null) && "find your address or use your location",
    addr.latitude != null && (!addr.address_line || !addr.city) && "fill in your street address and city",
    chosen.length > 0 && !deliveryChoice && "pick a delivery time",
  ].filter(Boolean) as string[];
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
  const itemCount = chosen.reduce((sum, s) => sum + (qty[s.id] ?? 0), 0);
  const estimate = chosen.reduce((sum, s) => sum + s.price_cents * (qty[s.id] ?? 0), 0);

  return (
    <div>
      {/* Cover photo with name and rating */}
      <section className="relative mb-6 overflow-hidden rounded-3xl shadow-raised">
        <CoverImage src={l.photo_url} name={l.business_name} className="h-56 w-full sm:h-72" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950/85 via-ink-900/30 to-transparent" />
        <Link to={`/search?lat=${lat}&lng=${lng}`} aria-label="All laundries"
          className="absolute left-4 top-4 grid h-10 w-10 place-items-center rounded-full bg-surface/90 text-slate-800 shadow-sm backdrop-blur hover:bg-surface">
          <Icon name="arrowLeft" className="h-5 w-5" />
        </Link>
        <div className="absolute inset-x-0 bottom-0 p-5 text-white sm:p-7">
          <span className="inline-flex items-center gap-1 rounded-full bg-surface/20 px-2.5 py-0.5 text-xs font-medium backdrop-blur">
            <Icon name="washer" className="h-3.5 w-3.5" /> Laundry
          </span>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{l.business_name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-white/80">
            {l.rating_avg != null
              ? <span className="inline-flex items-center gap-1 font-medium text-white"><Icon name="star" className="h-4 w-4 fill-amber-400 text-amber-400" />{l.rating_avg.toFixed(1)} <span className="font-normal text-white/75">({l.rating_count} reviews)</span></span>
              : <span>No ratings yet</span>}
            <span className="inline-flex items-center gap-1"><Icon name="pin" className="h-4 w-4" />{[l.suburb, l.city].filter(Boolean).join(", ")}</span>
            {l.distance_km != null && <span>{l.distance_km.toFixed(1)} km away</span>}
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-5">
          <Card title="About">
            {l.description && <p className="mb-4 text-slate-700">{l.description}</p>}
            <div className="grid gap-4 sm:grid-cols-[1fr_220px]">
              <div className="space-y-2 text-sm text-slate-600">
                <p className="flex items-start gap-2"><Icon name="pin" className="mt-0.5 h-4 w-4 text-brand-600" />{[l.address_line, l.suburb, l.city].filter(Boolean).join(", ")}</p>
                {l.contact_phone && <p><a href={`tel:${l.contact_phone}`} className="inline-flex items-center gap-2 hover:text-slate-900"><Icon name="phone" className="h-4 w-4 text-brand-600" />{l.contact_phone}</a></p>}
                <p className="flex items-center gap-2"><Icon name="shield" className="h-4 w-4 text-brand-600" />Verified by LaundryConnect</p>
              </div>
              <div className="overflow-hidden rounded-2xl ring-1 ring-slate-100">
                <MapView height={140} zoom={14} points={[{ latitude: l.latitude, longitude: l.longitude, label: l.business_name, color: "green" }]} />
              </div>
            </div>
          </Card>

          <Card title={isCustomer ? "1. Choose your services" : "Services & prices"}
            description={isCustomer ? "Tap + to add. Per-kg amounts are an estimate." : undefined} padded={false}>
            <ul className="divide-y divide-slate-100">
              {l.services.map((s) => {
                const n = qty[s.id] ?? 0;
                const info = CATEGORY_INFO[s.category] ?? CATEGORY_INFO.other;
                return (
                  <li key={s.id} className={`flex items-center gap-3 px-4 py-4 transition sm:px-5 ${n > 0 ? "bg-brand-50/50" : ""}`}>
                    <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${n > 0 ? "bg-brand-600 text-white" : "bg-brand-50 text-brand-600"}`}>
                      <Icon name={info.icon} className="h-6 w-6" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-900">{s.name}</p>
                      <p className="text-sm font-semibold text-brand-600">{s.price_display}</p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                        <span className="inline-flex items-center gap-1"><Icon name="clock" className="h-3 w-3" />ready in {s.turnaround_hours} h</span>
                        {s.min_quantity > 1 && <span>· min {s.min_quantity} {UNIT_LABEL[s.pricing_unit]}</span>}
                      </p>
                    </div>
                    {isCustomer && (
                      <div className="flex shrink-0 items-center gap-1.5">
                        <button type="button" aria-label={`Less ${s.name}`} disabled={n === 0} onClick={() => setQuantity(s.id, n - 1)}
                          className="grid h-8 w-8 place-items-center rounded-full text-lg leading-none text-brand-600 ring-1 ring-brand-200 transition hover:bg-brand-50 disabled:text-slate-300 disabled:ring-slate-200">−</button>
                        <input type="number" min={0} max={100} aria-label={`Quantity of ${s.name}`} value={n}
                          onChange={(e) => setQuantity(s.id, Number(e.target.value))}
                          className="h-8 w-10 rounded-lg bg-transparent text-center text-sm font-semibold tabular-nums outline-none [appearance:textfield] focus:bg-surface focus:ring-2 focus:ring-brand-600 [&::-webkit-inner-spin-button]:appearance-none" />
                        <button type="button" aria-label={`More ${s.name}`} onClick={() => setQuantity(s.id, n + 1)}
                          className="grid h-8 w-8 place-items-center rounded-full bg-brand-600 text-lg leading-none text-white shadow-sm shadow-brand-600/30 transition hover:bg-deep">+</button>
                      </div>
                    )}
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

        <aside id="book" className="scroll-mt-20">
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
                    <>
                      <Button size="lg" className="w-full" busy={quoting.busy} disabled={!ready} onClick={getQuote}>See price</Button>
                      {!ready && missing.length > 0 && (
                        <p className="flex items-start gap-1.5 text-xs text-slate-500">
                          <Icon name="info" className="mt-px h-3.5 w-3.5 shrink-0" />
                          <span>To see the price, {missing.join(", then ")}.</span>
                        </p>
                      )}
                    </>
                  )}
                  {quote && <p className="text-center text-xs text-slate-500">You'll pay on the next screen.</p>}
                  {chosen.length > 0 && !quote && (
                    <div className="fixed inset-x-3 bottom-[76px] z-20 flex items-center gap-3 rounded-2xl bg-ink-900 p-3 pl-4 text-white shadow-raised lg:hidden">
                      <span className="grid h-10 w-10 place-items-center rounded-xl bg-surface/10"><Icon name="washer" /></span>
                      <div className="min-w-0 flex-1 leading-tight">
                        <p className="text-sm font-semibold">{itemCount} item{itemCount === 1 ? "" : "s"} · {rands(estimate)}</p>
                        <p className="text-xs text-slate-400">plus collection & delivery</p>
                      </div>
                      <button type="button" onClick={() => document.getElementById("book")?.scrollIntoView({ behavior: "smooth" })}
                        className="rounded-full bg-brand-500 px-5 py-2 text-sm font-semibold text-white hover:bg-brand-400">Proceed</button>
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        </aside>
      </div>
    </div>
  );
}
