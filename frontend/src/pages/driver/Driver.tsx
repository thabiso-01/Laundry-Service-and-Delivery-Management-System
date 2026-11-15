import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { DriverJob, JobBoardItem } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Alert, Badge, Button, Card, Checkbox, Empty, Input, KeyValue, PageTitle, Spinner, Stars, StatusBadge } from "../../components/ui";
import type { Stop } from "../../api/types";
import { BagCodeField } from "../../components/QrScanner";
import { MapView } from "../../components/MapView";
import { DEFAULT_LOCATION, currentPosition, osmLink, rands, windowText } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

interface Ratings { rating_avg: number | null; rating_count: number }

function useDriverPosition() {
  const [pos, setPos] = useState(DEFAULT_LOCATION);
  const [known, setKnown] = useState(false);
  useEffect(() => {
    currentPosition().then((p) => { setPos(p); setKnown(true); }).catch(() => undefined);
  }, []);
  return { pos, known };
}

// UR-009: see and accept jobs. SEC-004: the API only lets approved drivers in.
export function DriverHome() {
  const { me, refresh } = useAuth();
  const navigate = useNavigate();
  const approved = me?.driver?.verification_status === "approved";
  const online = Boolean(me?.driver?.is_available);
  const { pos, known } = useDriverPosition();
  const mine = useAsync(() => approved ? api<DriverJob[]>("/api/driver/jobs") : Promise.resolve([]), [approved]);
  const board = useAsync(
    () => approved && online ? api<JobBoardItem[]>(`/api/driver/jobs/available?lat=${pos.latitude}&lng=${pos.longitude}`) : Promise.resolve([]),
    [approved, online, pos.latitude, pos.longitude],
  );
  const ratings = useAsync(() => approved ? api<Ratings>("/api/driver/ratings") : Promise.resolve(null), [approved]);
  const { busy, error, run } = useAction();

  if (!me?.driver) return <Spinner />;
  if (!approved) {
    return (
      <div className="max-w-xl">
        <PageTitle>Driver</PageTitle>
        <Alert kind={me.driver.verification_status === "rejected" ? "error" : "warning"}>
          {me.driver.verification_status === "rejected"
            ? <>Your application wasn't approved: {me.driver.rejection_reason}</>
            : <>Your account is waiting for approval. Make sure all your <Link to="/documents" className="underline">documents</Link> are uploaded.</>}
        </Alert>
      </div>
    );
  }

  const toggle = () => void run(async () => {
    await api("/api/driver/availability", { method: "PATCH", json: { is_available: !online } });
    await refresh();
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageTitle sub={<Stars value={ratings.data?.rating_avg ?? null} count={ratings.data?.rating_count} />}>Jobs</PageTitle>
        <Button variant={online ? "secondary" : "primary"} busy={busy} onClick={toggle}>{online ? "Go offline" : "Go online"}</Button>
      </div>
      <Alert>{error}</Alert>

      <Card title="My active jobs">
        {mine.loading ? <Spinner /> : !mine.data?.length ? <Empty>No active jobs.</Empty> : (
          <ul className="divide-y divide-slate-100">
            {mine.data.map((j) => (
              <li key={j.id}>
                <Link to={`/driver/jobs/${j.id}`} className="flex flex-wrap items-center justify-between gap-2 py-3">
                  <div>
                    <p className="font-medium"><Badge color="blue">{j.kind}</Badge> {j.pickup.area} → {j.dropoff.area}</p>
                    <p className="text-sm text-slate-500">{windowText(j.window_start, j.window_end)} · {j.next_step}</p>
                  </div>
                  <StatusBadge status={j.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Available near you" actions={!known && <span className="text-xs text-slate-500">Location off: showing jobs near Johannesburg CBD</span>}>
        {!online ? <Empty>Go online to see jobs.</Empty> : board.loading ? <Spinner /> : board.error ? <Alert>{board.error}</Alert> : !board.data?.length ? <Empty>No open jobs nearby right now.</Empty> : (
          <ul className="divide-y divide-slate-100">
            {board.data.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium"><Badge color="blue">{j.kind}</Badge> {j.pickup_area} → {j.dropoff_area}</p>
                  <p className="text-sm text-slate-500">
                    {windowText(j.window_start, j.window_end)} · {j.distance_to_pickup_km.toFixed(1)} km to pickup · trip {j.trip_km.toFixed(1)} km
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-emerald-700">{j.fee_display}</span>
                  <Button busy={busy} onClick={() => void run(async () => { await api(`/api/driver/jobs/${j.id}/accept`, { method: "POST" }); navigate(`/driver/jobs/${j.id}`); })}>Accept</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function StopCard({ title, stop }: { title: string; stop: Stop }) {
  return (
    <Card title={title}>
      <KeyValue items={[
        ["Name", stop.name],
        ["Area", stop.area],
        ["Address", stop.address_line],
        ["Phone", stop.phone && <a href={`tel:${stop.phone}`} className="text-sky-700 underline">{stop.phone}</a>],
        ["Notes", stop.notes],
      ]} />
      {stop.latitude != null && stop.longitude != null && (
        <a href={osmLink(stop.latitude, stop.longitude)} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-sky-700 underline">Open in map</a>
      )}
    </Card>
  );
}

// Sends the driver's position every 15 s while the job page is open (SEC-021)
function useLocationSharing(jobId: string, active: boolean) {
  const [last, setLast] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!active || !navigator.geolocation) return;
    const send = () => currentPosition()
      .then((p) => api(`/api/driver/jobs/${jobId}/location`, { json: p }))
      .then(() => setLast(new Date().toLocaleTimeString("en-ZA")))
      .catch(() => undefined);
    void send();
    timer.current = window.setInterval(send, 15000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [jobId, active]);
  return last;
}

export function DriverJobPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: job, error, loading, reload } = useAsync(() => api<DriverJob>(`/api/driver/jobs/${id}`), [id]);
  const [otp, setOtp] = useState("");
  const [code, setCode] = useState("");
  const [seals, setSeals] = useState("");
  const [intact, setIntact] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const { busy, error: actionError, run } = useAction();
  const active = Boolean(job && ["assigned", "picked_up"].includes(job.status));
  const lastPing = useLocationSharing(id!, active);

  if (loading && !job) return <Spinner />;
  if (error || !job) return <Alert>{error}</Alert>;

  const handover = (path: string, body: Record<string, unknown>) => void run(async () => {
    // Clear the previous step's "Done" straight away, so it can't be mistaken
    // for this step's result while the request is still running (or if it fails)
    setMessage(null);
    const pos = await currentPosition().catch(() => DEFAULT_LOCATION);
    const out = await api<{ incident_reference?: string | null; location_flagged: boolean }>(`/api/driver/jobs/${job.id}/${path}`, { json: { ...body, ...pos } });
    setMessage(out.incident_reference ? `Done. A seal problem was recorded as ${out.incident_reference}.` : "Done ✔");
    setOtp(""); setCode(""); setSeals("");
    await reload();
  });
  const sealList = seals.split(/[\s,]+/).filter(Boolean);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{job.kind === "collection" ? "Collection" : "Delivery"} · <span className="font-mono">{job.order_number}</span></h1>
        <StatusBadge status={job.status} />
        <span className="font-semibold text-emerald-700">{rands(job.driver_fee_cents)}</span>
      </div>
      <p className="text-sm text-slate-600">{windowText(job.window_start, job.window_end)} · {job.item_count} item line(s)
        {active && <> · 📍 sharing location{lastPing && ` (last sent ${lastPing})`}</>}</p>

      {message && <Alert kind="success">{message}</Alert>}
      <Alert>{actionError}</Alert>

      {job.next_step && (
        <Card title={job.next_step}>
          {job.kind === "collection" && job.status === "assigned" && (
            <div className="space-y-3">
              <Input label="Seal number(s) you put on the bag" value={seals} onChange={(e) => setSeals(e.target.value)} placeholder="S1234" hint="Seal the bag in front of the customer first." />
              <Input label="Customer's collection code" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} />
              <Button busy={busy} disabled={otp.length !== 6 || !sealList.length} onClick={() => handover("collect", { otp, seal_numbers: sealList })}>Confirm collection</Button>
            </div>
          )}
          {job.kind === "collection" && job.status === "picked_up" && <p className="text-sm text-slate-600">Take the bag to the laundry. Staff will scan its label and check the seals.</p>}
          {job.kind === "delivery" && job.status === "assigned" && (
            <div className="space-y-3">
              <BagCodeField value={code} onChange={setCode} />
              <Input label="Seal number(s) on the clean bag" value={seals} onChange={(e) => setSeals(e.target.value)} />
              <Button busy={busy} disabled={!code || !sealList.length} onClick={() => handover("pickup", { code, seal_numbers: sealList })}>Confirm pickup</Button>
            </div>
          )}
          {job.kind === "delivery" && job.status === "picked_up" && (
            <div className="space-y-3">
              <Checkbox checked={intact} onChange={(e) => setIntact(e.target.checked)} label="The customer checked the seals and they are intact" />
              <Input label="Customer's delivery code" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} />
              <Button busy={busy} disabled={otp.length !== 6} onClick={() => handover("deliver", { otp, seals_intact: intact })}>Confirm delivery</Button>
            </div>
          )}
        </Card>
      )}

      {job.pickup.latitude != null && job.dropoff.latitude != null && (
        <MapView height={260} points={[
          { latitude: job.pickup.latitude, longitude: job.pickup.longitude!, label: `Pick up: ${job.pickup.name}`, color: "blue" },
          { latitude: job.dropoff.latitude, longitude: job.dropoff.longitude!, label: `Drop off: ${job.dropoff.name}`, color: "green" },
        ]} line={[[job.pickup.latitude, job.pickup.longitude!], [job.dropoff.latitude, job.dropoff.longitude!]]} />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <StopCard title="Pick up from" stop={job.pickup} />
        <StopCard title="Drop off at" stop={job.dropoff} />
      </div>

      {job.status === "assigned" && (
        <Button variant="secondary" busy={busy} onClick={() => {
          const reason = prompt("Why can't you do this job?");
          if (reason && reason.length >= 3) void run(async () => { await api(`/api/driver/jobs/${job.id}/release`, { json: { reason } }); navigate("/driver"); });
        }}>Give this job back</Button>
      )}
    </div>
  );
}
