import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { DriverJob, JobBoardItem, Stop } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Icon } from "../../components/icons";
import { MapView } from "../../components/MapView";
import { BagCodeField } from "../../components/QrScanner";
import { Alert, Badge, Button, Card, Checkbox, Empty, HeroHeader, Input, KeyValue, ListRow, PageTitle, Spinner, StatusBadge, heroButton } from "../../components/ui";
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

function KindBadge({ kind }: { kind: string }) {
  return <Badge color={kind === "collection" ? "blue" : "purple"}>{kind === "collection" ? "Collection" : "Delivery"}</Badge>;
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
    const rejected = me.driver.verification_status === "rejected";
    return (
      <div className="max-w-xl">
        <PageTitle>Jobs</PageTitle>
        <Alert kind={rejected ? "error" : "warning"} title={rejected ? "Application not approved" : "Waiting for approval"}>
          {rejected
            ? <>{me.driver.rejection_reason}</>
            : <>We check every driver before they can take jobs. Make sure all your <Link to="/documents" className="font-medium underline">documents</Link> are uploaded.</>}
        </Alert>
      </div>
    );
  }

  const toggle = () => void run(async () => {
    await api("/api/driver/availability", { method: "PATCH", json: { is_available: !online } });
    await refresh();
  });

  return (
    <div>
      <HeroHeader title={`Hi, ${me.full_name.split(" ")[0]}!`}
        sub={ratings.data?.rating_avg != null
          ? <span className="inline-flex items-center gap-1"><Icon name="star" className="h-4 w-4 fill-amber-300 text-amber-300" />{ratings.data.rating_avg.toFixed(1)} from {ratings.data.rating_count} rating{ratings.data.rating_count === 1 ? "" : "s"}</span>
          : "No ratings yet"}>
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-white/10 p-4 ring-1 ring-white/15 backdrop-blur">
          <div className="flex items-center gap-3">
            <span className={`grid h-11 w-11 place-items-center rounded-full ${online ? "bg-emerald-400 text-emerald-950" : "bg-white/15 text-white"}`}>
              <Icon name="power" />
            </span>
            <div>
              <p className="font-semibold">{online ? "You're online" : "You're offline"}</p>
              <p className="text-sm text-brand-100">{online ? "New jobs near you appear below." : "Go online to see and accept jobs."}</p>
            </div>
          </div>
          <button type="button" className={heroButton} disabled={busy} onClick={toggle}>
            {busy && <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />}
            {online ? "Go offline" : "Go online"}
          </button>
        </div>
      </HeroHeader>
      <div className="mb-4 empty:hidden"><Alert>{error}</Alert></div>

      <div className="space-y-6">
        <Card title="My active jobs" padded={false}>
          {mine.loading ? <Spinner /> : !mine.data?.length ? <Empty icon="truck">No active jobs. Accept one below.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {mine.data.map((j) => (
                <li key={j.id}>
                  <ListRow to={`/driver/jobs/${j.id}`}>
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900"><KindBadge kind={j.kind} /> {j.pickup.area} <Icon name="arrowRight" className="h-3.5 w-3.5 text-slate-400" /> {j.dropoff.area}</p>
                      <p className="mt-0.5 text-sm text-slate-500">{windowText(j.window_start, j.window_end)} · <span className="font-medium text-brand-700">{j.next_step}</span></p>
                    </div>
                    <StatusBadge status={j.status} />
                  </ListRow>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Available near you" padded={false}
          actions={!known && <span className="text-xs text-slate-500">Location off: showing jobs near Johannesburg CBD</span>}>
          {!online ? <Empty icon="power">Go online to see jobs.</Empty> : board.loading ? <Spinner /> : board.error ? <div className="p-4"><Alert>{board.error}</Alert></div> : !board.data?.length ? <Empty icon="inbox">No open jobs nearby right now.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {board.data.map((j) => (
                <li key={j.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900"><KindBadge kind={j.kind} /> {j.pickup_area} <Icon name="arrowRight" className="h-3.5 w-3.5 text-slate-400" /> {j.dropoff_area}</p>
                    <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-slate-500">
                      <span className="inline-flex items-center gap-1"><Icon name="clock" className="h-3.5 w-3.5" />{windowText(j.window_start, j.window_end)}</span>
                      <span className="inline-flex items-center gap-1"><Icon name="pin" className="h-3.5 w-3.5" />{j.distance_to_pickup_km.toFixed(1)} km to pickup</span>
                      <span className="inline-flex items-center gap-1"><Icon name="route" className="h-3.5 w-3.5" />trip {j.trip_km.toFixed(1)} km</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-lg font-semibold text-emerald-700">{j.fee_display}</span>
                    <Button busy={busy} onClick={() => void run(async () => { await api(`/api/driver/jobs/${j.id}/accept`, { method: "POST" }); navigate(`/driver/jobs/${j.id}`); })}>Accept</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function StopCard({ title, stop, tone }: { title: string; stop: Stop; tone: "blue" | "green" }) {
  return (
    <Card title={<span className="inline-flex items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${tone === "blue" ? "bg-brand-600" : "bg-emerald-600"}`} />{title}</span>}
      actions={stop.latitude != null && stop.longitude != null && (
        <a href={osmLink(stop.latitude, stop.longitude)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
          <Icon name="navigation" className="h-3.5 w-3.5" /> Map
        </a>
      )}>
      <KeyValue items={[
        ["Name", stop.name],
        ["Area", stop.area],
        ["Address", stop.address_line],
        ["Phone", stop.phone && <a href={`tel:${stop.phone}`} className="text-brand-700 hover:underline">{stop.phone}</a>],
        ["Notes", stop.notes],
      ]} />
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

// The three steps of a job, so the driver always sees where they are
function JobSteps({ job }: { job: DriverJob }) {
  const steps = job.kind === "collection"
    ? ["Accepted", "Collected from customer", "Delivered to laundry"]
    : ["Accepted", "Picked up at laundry", "Delivered to customer"];
  const at = job.status === "assigned" ? 1 : job.status === "picked_up" ? 2 : job.status === "completed" ? 3 : 0;
  return (
    <ol className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={`grid h-6 w-6 place-items-center rounded-full text-xs font-semibold ${i < at ? "bg-brand-600 text-white" : i === at ? "bg-white text-brand-700 ring-2 ring-brand-600" : "bg-slate-100 text-slate-400"}`}>
            {i < at ? <Icon name="check" className="h-3.5 w-3.5" /> : i + 1}
          </span>
          <span className={i <= at ? "font-medium text-slate-900" : "text-slate-400"}>{s}</span>
        </li>
      ))}
    </ol>
  );
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
    // Clear the previous step's message straight away, so it can't be mistaken
    // for this step's result while the request is still running (or if it fails)
    setMessage(null);
    const pos = await currentPosition().catch(() => DEFAULT_LOCATION);
    const out = await api<{ incident_reference?: string | null; location_flagged: boolean }>(`/api/driver/jobs/${job.id}/${path}`, { json: { ...body, ...pos } });
    setMessage(out.incident_reference ? `Step confirmed. A seal problem was recorded as ${out.incident_reference}.` : "Step confirmed.");
    setOtp(""); setCode(""); setSeals("");
    await reload();
  });
  const sealList = seals.split(/[\s,]+/).filter(Boolean);

  return (
    <div>
      <PageTitle back={{ to: "/driver", label: "Jobs" }}
        sub={<span className="flex flex-wrap items-center gap-x-2">{windowText(job.window_start, job.window_end)} · {job.item_count} item line(s)
          {active && <span className="inline-flex items-center gap-1.5 text-emerald-700"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />Sharing location{lastPing && ` (last sent ${lastPing})`}</span>}
        </span>}
        actions={<><span className="text-lg font-semibold text-emerald-700">{rands(job.driver_fee_cents)}</span><StatusBadge status={job.status} /></>}>
        {job.kind === "collection" ? "Collection" : "Delivery"} · <span className="font-mono">{job.order_number}</span>
      </PageTitle>

      <div className="space-y-5">
        <Card><JobSteps job={job} /></Card>

        {message && <Alert kind="success">{message}</Alert>}
        <Alert>{actionError}</Alert>

        {job.next_step && (
          <Card title={job.next_step} className="ring-2 ring-brand-100">
            {job.kind === "collection" && job.status === "assigned" && (
              <div className="space-y-4">
                <Input label="Seal number(s) you put on the bag" value={seals} onChange={(e) => setSeals(e.target.value)} placeholder="S1234" hint="Seal the bag in front of the customer first." />
                <Input label="Customer's collection code" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)}
                  className="font-mono text-lg tracking-[0.3em]" hint="The customer reads it from their phone. Never accept it over the phone." />
                <Button size="lg" className="w-full sm:w-auto" busy={busy} disabled={otp.length !== 6 || !sealList.length} onClick={() => handover("collect", { otp, seal_numbers: sealList })}>Confirm collection</Button>
              </div>
            )}
            {job.kind === "collection" && job.status === "picked_up" && <p className="text-sm text-slate-600">Take the bag to the laundry. Staff will scan its label and check the seals.</p>}
            {job.kind === "delivery" && job.status === "assigned" && (
              <div className="space-y-4">
                <BagCodeField value={code} onChange={setCode} />
                <Input label="Seal number(s) on the clean bag" value={seals} onChange={(e) => setSeals(e.target.value)} />
                <Button size="lg" className="w-full sm:w-auto" busy={busy} disabled={!code || !sealList.length} onClick={() => handover("pickup", { code, seal_numbers: sealList })}>Confirm pickup</Button>
              </div>
            )}
            {job.kind === "delivery" && job.status === "picked_up" && (
              <div className="space-y-4">
                <Checkbox checked={intact} onChange={(e) => setIntact(e.target.checked)} label="The customer checked the seals and they are intact" />
                <Input label="Customer's delivery code" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)}
                  className="font-mono text-lg tracking-[0.3em]" />
                <Button size="lg" className="w-full sm:w-auto" busy={busy} disabled={otp.length !== 6} onClick={() => handover("deliver", { otp, seals_intact: intact })}>Confirm delivery</Button>
              </div>
            )}
          </Card>
        )}

        {job.pickup.latitude != null && job.dropoff.latitude != null && (
          <div className="overflow-hidden rounded-xl border border-slate-200 shadow-card">
            <MapView height={260} points={[
              { latitude: job.pickup.latitude, longitude: job.pickup.longitude!, label: `Pick up: ${job.pickup.name}`, color: "blue" },
              { latitude: job.dropoff.latitude, longitude: job.dropoff.longitude!, label: `Drop off: ${job.dropoff.name}`, color: "green" },
            ]} line={[[job.pickup.latitude, job.pickup.longitude!], [job.dropoff.latitude, job.dropoff.longitude!]]} />
          </div>
        )}

        <div className="grid gap-5 md:grid-cols-2">
          <StopCard title="Pick up from" stop={job.pickup} tone="blue" />
          <StopCard title="Drop off at" stop={job.dropoff} tone="green" />
        </div>

        {job.status === "assigned" && (
          <div className="flex justify-end">
            <Button variant="ghost" className="text-rose-700 hover:bg-rose-50" busy={busy} onClick={() => {
              const reason = prompt("Why can't you do this job?");
              if (reason && reason.length >= 3) void run(async () => { await api(`/api/driver/jobs/${job.id}/release`, { json: { reason } }); navigate("/driver"); });
            }}>Give this job back</Button>
          </div>
        )}
      </div>
    </div>
  );
}
