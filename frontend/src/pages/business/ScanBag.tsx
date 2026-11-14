import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import { QrScanner } from "../../components/QrScanner";
import { Alert, Button, Card, Input, KeyValue, PageTitle, StatusBadge } from "../../components/ui";
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
    <div className="max-w-lg space-y-4">
      <PageTitle sub="Check which order a bag belongs to. Every scan is recorded.">Scan a bag</PageTitle>
      <Card>
        <div className="space-y-3">
          <Button className="w-full py-3 text-base" onClick={() => setScanning(true)}>📷 Scan with camera</Button>
          <div className="flex items-end gap-2">
            <div className="flex-1"><Input label="…or type the code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="LCQ1.LC-…" /></div>
            <Button variant="secondary" className="mb-0.5" busy={busy} disabled={!code} onClick={() => check(code.trim())}>Check</Button>
          </div>
        </div>
      </Card>
      {problem && <Alert>⚠ {problem}</Alert>}
      {result && (
        <Card title={<span className="text-emerald-700">✔ Genuine label</span>}>
          <KeyValue items={[
            ["Order", <span key="n" className="font-mono">{result.order_number}</span>],
            ["Status", <StatusBadge key="s" status={result.status} />],
            ["Customer", result.customer_name],
            ["Item lines", String(result.item_count)],
          ]} />
          <Link to={`/business/orders/${result.order_id}`} className="mt-3 inline-block"><Button variant="secondary">Open order</Button></Link>
        </Card>
      )}
      {scanning && <QrScanner onClose={() => setScanning(false)} onResult={(value) => { setScanning(false); setCode(value); check(value); }} />}
    </div>
  );
}
