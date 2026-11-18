import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Icon, type IconName } from "../../components/icons";
import { api } from "../../api/client";
import type { Order, OrderSummary, Page } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AuthImage, EvidenceCards, Money, OrderHeader, OrderProgress, Schedule, Timeline } from "../../components/order";
import { BagCodeField } from "../../components/QrScanner";
import { Alert, Button, ButtonLink, Card, Checkbox, Empty, HeroHeader, HeroStat, Input, KeyValue, ListRow, Spinner, StatusBadge, Tabs, TextArea, heroButton } from "../../components/ui";
import { rands, windowText } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

const TABS: [string, string[]][] = [
  ["Needs action", ["placed", "collected", "received", "processing"]],
  ["In progress", ["accepted", "ready", "out_for_delivery"]],
  ["Finished", ["delivered", "cancelled", "declined"]],
];

function VerificationBanner() {
  const { me } = useAuth();
  const b = me?.business;
  if (!b || b.business_verification_status === "approved") return null;
  return (
    <div className="mb-6">
      <Alert kind={b.business_verification_status === "rejected" ? "error" : "warning"}
        title={b.business_verification_status === "rejected" ? "Not approved" : "Waiting for verification"}>
        {b.business_verification_status === "rejected"
          ? <>Your business was not approved: {b.business_rejection_reason}. Update your <Link to="/documents" className="underline">documents</Link>.</>
          : <>Your business is waiting for verification. Upload your <Link to="/documents" className="underline">documents</Link> and set up your <Link to="/business/services" className="underline">services</Link> meanwhile.</>}
      </Alert>
    </div>
  );
}

// UR-010 receive and manage orders
const STATS: [string, string, IconName, "amber" | "violet" | "brand" | "emerald"][] = [
  ["placed", "New orders", "inbox", "amber"],
  ["received", "Checked in", "package", "violet"],
  ["processing", "Being cleaned", "washer", "brand"],
  ["ready", "Ready for delivery", "checkCircle", "emerald"],
];

export function BusinessOrders() {
  const { me } = useAuth();
  const [tab, setTab] = useState(0);
  const approved = me?.business?.business_verification_status === "approved";
  const counts = useAsync(() => approved ? api<{ counts: Record<string, number> }>("/api/business/orders/summary") : Promise.resolve(null), [approved]);
  const list = useAsync(() => {
    if (!approved) return Promise.resolve(null);
    const q = new URLSearchParams();
    TABS[tab][1].forEach((s) => q.append("status", s));
    return api<Page<OrderSummary>>(`/api/business/orders?${q}`);
  }, [tab, approved]);
  const c = counts.data?.counts ?? {};

  return (
    <div>
      <HeroHeader title={`Hi, ${me?.full_name.split(" ")[0]}!`}
        sub={<span className="inline-flex items-center gap-1.5"><Icon name="store" className="h-4 w-4" />{me?.business?.business_name}</span>}
        actions={approved && <Link to="/business/scan" className={heroButton}><Icon name="scan" className="h-4 w-4" />Scan a bag</Link>}>
        {approved && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {STATS.map(([s, text, icon]) => <HeroStat key={s} label={text} value={c[s] ?? "–"} icon={icon} />)}
          </div>
        )}
      </HeroHeader>
      <VerificationBanner />
      {approved && (
        <>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">Orders</h2>
          <div className="mb-4">
            <Tabs value={tab} onChange={setTab} items={TABS.map(([name, statuses]) => ({
              label: name, count: tab === 2 ? undefined : statuses.reduce((n, s) => n + (c[s] ?? 0), 0) || undefined,
            }))} />
          </div>
          {list.loading ? <Spinner /> : list.error ? <Alert>{list.error}</Alert> : !list.data?.items.length ? (
            <Card><Empty icon="inbox" title="Nothing here right now">New orders appear here as soon as customers pay.</Empty></Card>
          ) : (
            <Card padded={false}>
              <ul className="stagger divide-y divide-slate-100">
                {list.data.items.map((o) => (
                  <li key={o.id}>
                    <ListRow to={`/business/orders/${o.id}`}>
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-semibold text-slate-900">{o.order_number}</p>
                        <p className="text-sm text-slate-500">Collect {windowText(o.collection_window_start, o.collection_window_end)}</p>
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
        </>
      )}
    </div>
  );
}

// What the laundry is waiting for when there's nothing for them to do
const WAITING: Record<string, string> = {
  accepted: "Nothing to do yet. A driver is on the way to collect the bag from the customer.",
  out_for_delivery: "A driver is delivering the bag to the customer.",
  delivered: "Delivered to the customer. This order is complete.",
  cancelled: "This order was cancelled.",
  declined: "You declined this order.",
};

function Actions({ order, reload }: { order: Order; reload: () => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [code, setCode] = useState("");
  const [seals, setSeals] = useState("");
  const [intact, setIntact] = useState(true);
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [result, setResult] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const go = (fn: () => Promise<unknown>) => void run(async () => { setResult(null); await fn(); await reload(); });
  const post = (path: string, json: unknown = {}) => api<Order>(`/api/business/orders/${order.id}/${path}`, { json });

  if (order.status === "placed") {
    return (
      <Card title="New order: accept or decline" className="ring-2 ring-brand-100">
        {order.paid_cents < order.total_cents ? (
          <Alert kind="info">Waiting for the customer to pay.</Alert>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">The customer has paid. Accept to send a driver to collect the bag.</p>
            <Button size="lg" icon="check" busy={busy} onClick={() => go(() => post("accept"))}>Accept order</Button>
            <details className="group rounded-lg border border-slate-200 p-3">
              <summary className="cursor-pointer text-sm font-medium text-slate-600">Can't take it? Decline instead</summary>
              <div className="mt-3 space-y-3">
                <TextArea label="Reason (shown to the customer)" value={reason} onChange={(e) => setReason(e.target.value)} />
                <Button variant="danger" busy={busy} disabled={reason.length < 5} onClick={() => go(() => post("decline", { reason }))}>Decline order</Button>
              </div>
            </details>
          </div>
        )}
        <div className="mt-3"><Alert>{error}</Alert></div>
      </Card>
    );
  }
  if (order.status === "collected") {
    return (
      <Card title="Receive the bag from the driver" description="Scan the bag's QR label and check the seals before you sign for it." className="ring-2 ring-brand-100">
        <div className="space-y-3">
          <BagCodeField value={code} onChange={setCode} />
          <Input label="Seal numbers on the bag" value={seals} onChange={(e) => setSeals(e.target.value)} placeholder="S1234, S5678" hint="Separate several seals with commas." />
          <Checkbox checked={intact} onChange={(e) => setIntact(e.target.checked)} label="All seals are intact and untouched" />
          <Button busy={busy} disabled={!code} onClick={() => go(async () => {
            const out = await post("receive", { code, seal_numbers: seals.split(/[\s,]+/).filter(Boolean), seals_intact: intact });
            if (out.seal_incident_reference) setResult(`Seal problem recorded as incident ${out.seal_incident_reference}. Keep the bag aside for inspection.`);
          })}>Confirm received</Button>
          <Alert>{error}</Alert>
        </div>
      </Card>
    );
  }
  const perKg = order.items.filter((i) => i.pricing_unit === "per_kg");
  const needsAction = ["received", "processing"].includes(order.status);
  return (
    <Card title="What to do now" className={needsAction ? "ring-2 ring-brand-100" : ""}>
      <div className="space-y-4">
        {result && <Alert kind="warning">{result}</Alert>}
        {order.is_estimate && ["received", "processing"].includes(order.status) && perKg.length > 0 && (
          <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/60 p-4">
            <p className="text-sm font-semibold text-slate-900">Weigh the per-kg items</p>
            {perKg.map((i) => (
              <Input key={i.service_id} type="number" min={1} label={`${i.service_name} – estimated ${i.quantity} kg`}
                value={weights[i.service_id] ?? String(i.quantity)} onChange={(e) => setWeights({ ...weights, [i.service_id]: e.target.value })} />
            ))}
            <Button variant="secondary" busy={busy} onClick={() => go(() => post("weigh", { lines: perKg.map((i) => ({ service_id: i.service_id, actual_quantity: Number(weights[i.service_id] ?? i.quantity) })) }))}>Save weights</Button>
          </div>
        )}
        {order.status === "received" && <Button busy={busy} onClick={() => go(() => post("status", { status: "processing" }))}>Start processing</Button>}
        {order.status === "processing" && (
          <Button busy={busy} disabled={order.is_estimate || order.balance_cents > 0} onClick={() => go(() => post("status", { status: "ready" }))}>Mark ready for delivery</Button>
        )}
        {order.balance_cents > 0 && <Alert kind="info">Waiting for the customer to pay the balance of {rands(order.balance_cents)}.</Alert>}
        {order.status === "ready" && <p className="text-sm text-slate-600">A driver will collect the bag. They scan its QR label to take it.</p>}
        {WAITING[order.status] && <p className="text-sm text-slate-600">{WAITING[order.status]}</p>}
        <Alert>{error}</Alert>
      </div>
    </Card>
  );
}

export function BusinessOrderDetail() {
  const { id } = useParams();
  const { data: order, error, loading, reload } = useAsync(() => api<Order>(`/api/business/orders/${id}`), [id]);
  if (loading && !order) return <Spinner />;
  if (error || !order) return <Alert>{error}</Alert>;
  return (
    <div>
      <OrderHeader order={order} back={{ to: "/business", label: "Orders" }} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <OrderProgress order={order} explain={false} />
          <Actions order={order} reload={reload} />
          <EvidenceCards order={order} />
          <Card title="Activity"><Timeline events={order.history} /></Card>
        </div>
        <div className="space-y-5">
          <Card title="Customer"><KeyValue items={[["Name", order.customer_name], ["Phone", order.customer_phone && <a href={`tel:${order.customer_phone}`} className="text-brand-700 hover:underline">{order.customer_phone}</a>]]} /></Card>
          <Card title="Items"><Money order={order} /></Card>
          <Card title="Collection & delivery"><Schedule order={order} /></Card>
          <Card title="Bag label" actions={<Button variant="ghost" size="sm" icon="print" className="no-print" onClick={() => window.print()}>Print</Button>}>
            <AuthImage path={`/api/business/orders/${order.id}/qr`} alt="Order QR label" className="mx-auto h-44 w-44" />
            <p className="mt-2 text-center font-mono text-sm font-medium">{order.order_number}</p>
          </Card>
          <ButtonLink to={`/incidents/new?order=${order.id}`} variant="secondary" icon="flag" className="w-full">Report a problem</ButtonLink>
        </div>
      </div>
    </div>
  );
}
