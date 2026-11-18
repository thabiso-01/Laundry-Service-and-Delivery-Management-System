import { useState } from "react";
import { ApiError, api } from "../../api/client";
import { Icon } from "../../components/icons";
import { QrScanner } from "../../components/QrScanner";
import { Alert, Button, ButtonLink, Card, KeyValue, PageTitle, StatusBadge } from "../../components/ui";
import { useAction } from "../../lib/useAsync";

interface ScanResult { order_id: string; order_number: string; status: string; customer_name: string; item_count: number }

// SEC-011 / SEC-012: check any bag at the counter. Forged, replaced or other
// laundries' labels are rejected and logged.
export function ScanBag() {
  const [scanning, setScanning] = useState(false);
  const [code, setCode] = useState("");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { busy, run } = useAction();

  const check = (value: string) => void run(async () => {
    setResult(null);
    setProblem(null);
    try {
      setResult(await api<ScanResult>("/api/scan", { json: { code: value } }));
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : String(e));
    }
  });

  return (
    <div className="mx-auto max-w-lg">
      <PageTitle sub="Check which order a bag belongs to. Every scan is recorded.">Scan a bag</PageTitle>
      <div className="space-y-5">
        <Card>
          <div className="space-y-5">
            <button onClick={() => setScanning(true)}
              className="flex w-full flex-col items-center gap-3 rounded-xl border-2 border-dashed border-brand-200 bg-brand-50/50 px-4 py-8 text-brand-800 transition hover:border-brand-400 hover:bg-brand-50">
              <span className="grid h-14 w-14 place-items-center rounded-full bg-deep text-white shadow-sm"><Icon name="camera" className="h-6 w-6" /></span>
              <span className="font-semibold">Scan with camera</span>
              <span className="text-sm text-slate-500">Point it at the QR label on the bag</span>
            </button>
            <div className="flex items-center gap-3 text-xs font-medium text-slate-400 uppercase"><span className="h-px flex-1 bg-slate-200" />or type the code<span className="h-px flex-1 bg-slate-200" /></div>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim()) check(code.trim()); }}>
              <input aria-label="Bag code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="LCQ1.LC-…"
                className="block h-10 min-w-0 flex-1 rounded-lg border-0 px-3 font-mono text-sm shadow-sm ring-1 ring-inset ring-slate-300 outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600" />
              <Button type="submit" variant="secondary" busy={busy} disabled={!code}>Check</Button>
            </form>
          </div>
        </Card>
        {problem && <Alert title="Label not accepted">{problem}</Alert>}
        {result && (
          <Card title={<span className="inline-flex items-center gap-2 text-emerald-700"><Icon name="checkCircle" className="h-5 w-5" /> Genuine label</span>}
            actions={<ButtonLink to={`/business/orders/${result.order_id}`} size="sm">Open order</ButtonLink>}>
            <KeyValue items={[
              ["Order", <span key="n" className="font-mono">{result.order_number}</span>],
              ["Status", <StatusBadge key="s" status={result.status} />],
              ["Customer", result.customer_name],
              ["Item lines", String(result.item_count)],
            ]} />
          </Card>
        )}
      </div>
      {scanning && <QrScanner onClose={() => setScanning(false)} onResult={(value) => { setScanning(false); setCode(value); check(value); }} />}
    </div>
  );
}
