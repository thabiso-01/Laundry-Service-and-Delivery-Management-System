import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Order, OrderSummary, Page } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AuthImage, EvidenceCards, Money, OrderHeader, Schedule, Timeline } from "../../components/order";
import { BagCodeField } from "../../components/QrScanner";
import { Alert, Button, Card, Checkbox, Empty, Input, KeyValue, PageTitle, Spinner, StatusBadge, TextArea } from "../../components/ui";
import { label, rands, windowText } from "../../lib/format";
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
    <div className="mb-4">
      <Alert kind={b.business_verification_status === "rejected" ? "error" : "warning"}>
        {b.business_verification_status === "rejected"
          ? <>Your business was not approved: {b.business_rejection_reason}. Update your <Link to="/documents" className="underline">documents</Link>.</>
          : <>Your business is waiting for verification. Upload your <Link to="/documents" className="underline">documents</Link> and set up your <Link to="/business/services" className="underline">services</Link> meanwhile.</>}
      </Alert>
    </div>
  );
}

// UR-010 receive and manage orders
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

  return (
    <div>
      <PageTitle sub={me?.business?.business_name}>Orders</PageTitle>
      <VerificationBanner />
      {approved && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {["placed", "received", "processing", "ready"].map((s) => (
              <Card key={s}><p className="text-xs text-slate-500">{label(s)}</p><p className="text-2xl font-bold">{counts.data?.counts[s] ?? "–"}</p></Card>
            ))}
          </div>
          <div className="mb-3 flex gap-1">
            {TABS.map(([name], i) => (
              <button key={name} onClick={() => setTab(i)} className={`rounded-lg px-3 py-1.5 text-sm ${tab === i ? "bg-sky-700 text-white" : "bg-white text-slate-700 border border-slate-200"}`}>{name}</button>
            ))}
          </div>
          {list.loading ? <Spinner /> : list.error ? <Alert>{list.error}</Alert> : !list.data?.items.length ? <Empty>Nothing here right now.</Empty> : (
            <div className="space-y-2">
              {list.data.items.map((o) => (
                <Link key={o.id} to={`/business/orders/${o.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-4 hover:border-sky-300">
                  <div>
                    <p className="font-mono font-semibold">{o.order_number}</p>
                    <p className="text-sm text-slate-500">Collect {windowText(o.collection_window_start, o.collection_window_end)}</p>
                  </div>
                  <div className="flex items-center gap-3"><span className="text-sm">{rands(o.total_cents)}</span><StatusBadge status={o.status} /></div>
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

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
      <Card title="New order">
        {order.paid_cents < order.total_cents ? (
          <Alert kind="info">Waiting for the customer to pay.</Alert>
        ) : (
          <div className="space-y-3">
            <Button busy={busy} onClick={() => go(() => post("accept"))}>Accept order</Button>
            <TextArea label="Or decline – reason (shown to the customer)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <Button variant="danger" busy={busy} disabled={reason.length < 5} onClick={() => go(() => post("decline", { reason }))}>Decline</Button>
          </div>
        )}
        <div className="mt-3"><Alert>{error}</Alert></div>
      </Card>
    );
  }
  if (order.status === "collected") {
    return (
      <Card title="Receive the bag from the driver">
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
  return (
    <Card title="Next step">
      <div className="space-y-3">
        {result && <Alert kind="warning">{result}</Alert>}
        {order.is_estimate && ["received", "processing"].includes(order.status) && perKg.length > 0 && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-3">
            <p className="text-sm font-medium">Weigh the per-kg items</p>
            {perKg.map((i) => (
              <Input key={i.service_id} type="number" min={1} label={`${i.service_name} – estimated ${i.quantity} kg`}
                value={weights[i.service_id] ?? String(i.quantity)} onChange={(e) => setWeights({ ...weights, [i.service_id]: e.target.value })} />
            ))}
            <Button busy={busy} onClick={() => go(() => post("weigh", { lines: perKg.map((i) => ({ service_id: i.service_id, actual_quantity: Number(weights[i.service_id] ?? i.quantity) })) }))}>Save weights</Button>
          </div>
        )}
        {order.status === "received" && <Button busy={busy} onClick={() => go(() => post("status", { status: "processing" }))}>Start processing</Button>}
        {order.status === "processing" && (
          <Button busy={busy} disabled={order.is_estimate || order.balance_cents > 0} onClick={() => go(() => post("status", { status: "ready" }))}>Mark ready for delivery</Button>
        )}
        {order.balance_cents > 0 && <Alert kind="info">Waiting for the customer to pay the balance of {rands(order.balance_cents)}.</Alert>}
        {order.status === "ready" && <p className="text-sm text-slate-600">A driver will collect the bag. They scan its QR label to take it.</p>}
        {["accepted", "out_for_delivery", "delivered", "cancelled", "declined"].includes(order.status) && <p className="text-sm text-slate-600">Nothing to do right now.</p>}
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
      <OrderHeader order={order} />
      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Actions order={order} reload={reload} />
          <Card title="History"><Timeline events={order.history} /></Card>
          <EvidenceCards order={order} />
        </div>
        <div className="space-y-4">
          <Card title="Customer"><KeyValue items={[["Name", order.customer_name], ["Phone", order.customer_phone]]} /></Card>
          <Card title="Items"><Money order={order} /></Card>
          <Card title="Schedule"><Schedule order={order} /></Card>
          <Card title="Bag label" actions={<a className="text-sm text-sky-700 underline" href="#" onClick={(e) => { e.preventDefault(); window.print(); }}>Print</a>}>
            <AuthImage path={`/api/business/orders/${order.id}/qr`} alt="Order QR label" className="mx-auto h-44 w-44" />
            <p className="mt-1 text-center font-mono text-sm">{order.order_number}</p>
          </Card>
          <Link to={`/incidents/new?order=${order.id}`}><Button variant="secondary" className="w-full">Report a problem</Button></Link>
        </div>
      </div>
    </div>
  );
}
