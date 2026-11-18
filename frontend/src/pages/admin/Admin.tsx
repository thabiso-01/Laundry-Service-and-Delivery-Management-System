import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiBlobUrl } from "../../api/client";
import type { AdminIncident, Doc, DocumentsOverview, Requirement, IncidentSummary, Page } from "../../api/types";
import { Icon } from "../../components/icons";
import { MapView } from "../../components/MapView";
import { AuthImage, Seals, Timeline } from "../../components/order";
import { Alert, Badge, Button, Card, Checkbox, Empty, HeroHeader, HeroStat, KeyValue, ListRow, PageTitle, Select, Spinner, StatusBadge, Tabs, TextArea } from "../../components/ui";

const STATUSES = ["pending", "approved", "rejected"];
import { label, osmLink, when } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

interface DriverReview { user_id: string; full_name: string; email: string; phone: string | null; id_number: string;
  vehicle_type: string | null; vehicle_registration: string | null; verification_status: string; rejection_reason: string | null; registered_at: string }
interface BusinessReview { id: string; business_name: string; registration_number: string | null; owner_name: string; owner_email: string;
  address_line: string | null; suburb: string | null; city: string | null; contact_phone: string | null;
  verification_status: string; rejection_reason: string | null; registered_at: string }

// ---------- Verification queue (UR-004, UAT-005) ----------

export function Verification() {
  const [status, setStatus] = useState("pending");
  const drivers = useAsync(() => api<Page<DriverReview>>(`/api/admin/drivers?status=${status}`), [status]);
  const businesses = useAsync(() => api<Page<BusinessReview>>(`/api/admin/businesses?status=${status}`), [status]);
  const docs = useAsync(() => api<Page<{ id: string }>>("/api/admin/documents?limit=1"));
  return (
    <div>
      <HeroHeader title="Verification" sub="Check drivers and laundries before they can work on the platform.">
        <div className="grid gap-3 sm:grid-cols-3">
          <HeroStat label="Documents to review" value={docs.data?.total ?? "–"} icon="file" />
          <HeroStat label={`${label(status)} drivers`} value={drivers.data?.total ?? "–"} icon="truck" />
          <HeroStat label={`${label(status)} laundries`} value={businesses.data?.total ?? "–"} icon="store" />
        </div>
      </HeroHeader>
      <div className="mb-4">
        <Tabs value={STATUSES.indexOf(status)} onChange={(i) => setStatus(STATUSES[i])} items={STATUSES.map((s) => ({ label: label(s) }))} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Drivers" padded={false}>
          {drivers.loading ? <Spinner /> : !drivers.data?.items.length ? <Empty icon="truck">No {status} drivers.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {drivers.data.items.map((d) => (
                <li key={d.user_id}>
                  <ListRow to={`/admin/drivers/${d.user_id}`}>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900">{d.full_name}</p>
                      <p className="truncate text-sm text-slate-500">{d.email} · {d.vehicle_type ?? "no vehicle"}</p>
                    </div>
                    <span className="text-xs text-slate-500">{when(d.registered_at)}</span>
                  </ListRow>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Laundries" padded={false}>
          {businesses.loading ? <Spinner /> : !businesses.data?.items.length ? <Empty icon="store">No {status} laundries.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {businesses.data.items.map((b) => (
                <li key={b.id}>
                  <ListRow to={`/admin/businesses/${b.id}`}>
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900">{b.business_name}</p>
                      <p className="truncate text-sm text-slate-500">{b.owner_name} · {b.city}</p>
                    </div>
                    <span className="text-xs text-slate-500">{when(b.registered_at)}</span>
                  </ListRow>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

// ---------- Reviewing one driver or laundry ----------

const DOC_NAME: Record<string, string> = { national_id: "SA ID", passport: "Passport", drivers_licence: "Driver's licence" };
const docName = (t: string) => DOC_NAME[t] ?? label(t);
const isPdf = (d: Doc) => d.original_filename.toLowerCase().endsWith(".pdf");

function DocumentReview({ overview, reload }: { overview: DocumentsOverview; reload: () => Promise<void> }) {
  const current = new Set(overview.requirements.map((r) => r.document_id).filter(Boolean));
  const older = overview.documents.filter((d) => !current.has(d.id));
  return (
    <Card title="Documents" description="Open each document, check it, then approve or reject it. Every time you open one, it's recorded in the audit log (POPIA)." padded={false}>
      <ul className="divide-y divide-slate-100">
        {overview.requirements.map((r) => (
          <DocumentRow key={r.name} req={r} doc={overview.documents.find((d) => d.id === r.document_id) ?? null} reload={reload} />
        ))}
      </ul>
      {older.length > 0 && (
        <details className="group border-t border-slate-100">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-slate-600 sm:px-5">
            Older uploads ({older.length})
            <Icon name="chevronRight" className="h-4 w-4 text-slate-400 transition group-open:rotate-90" />
          </summary>
          <ul className="divide-y divide-slate-100 border-t border-slate-100 px-4 sm:px-5">
            {older.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <span className="text-slate-700">{docName(d.document_type)} · {when(d.uploaded_at)}</span>
                <StatusBadge status={d.status} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function DocumentRow({ req, doc, reload }: { req: Requirement; doc: Doc | null; reload: () => Promise<void> }) {
  const { busy, error, run } = useAction();
  const [open, setOpen] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  const decide = (approve: boolean) => void run(async () => {
    await api(`/api/admin/documents/${doc!.id}/${approve ? "approve" : "reject"}`, { json: approve ? {} : { reason } });
    setRejecting(false);
    setReason("");
    await reload();
  });
  const view = async () => {
    if (isPdf(doc!)) window.open(await apiBlobUrl(`/api/admin/documents/${doc!.id}/file`), "_blank");
    else setOpen((o) => !o);
  };

  return (
    <li className="px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-slate-900">{req.name}</p>
          <p className="mt-0.5 text-sm text-slate-500">
            {doc ? <>{req.accepted_types.length > 1 && `${docName(doc.document_type)} · `}Uploaded {when(doc.uploaded_at)}</> : "Not uploaded yet"}
          </p>
          {doc?.status === "rejected" && doc.review_notes && <p className="mt-1 text-sm text-rose-700">Rejected: {doc.review_notes}</p>}
        </div>
        <StatusBadge status={req.status} />
      </div>

      {doc && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" icon={isPdf(doc) ? "file" : "search"} onClick={() => void view()}>
            {isPdf(doc) ? "Open PDF" : open ? "Hide photo" : "View photo"}
          </Button>
          {doc.status === "pending" && !rejecting && (
            <>
              <Button size="sm" icon="check" busy={busy} onClick={() => decide(true)}>Approve</Button>
              <Button size="sm" variant="ghost" onClick={() => setRejecting(true)}>Reject</Button>
            </>
          )}
        </div>
      )}

      {open && doc && !isPdf(doc) && (
        <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
          <AuthImage path={`/api/admin/documents/${doc.id}/file`} alt={`${req.name} of the applicant`} className="mx-auto max-h-[28rem] w-auto object-contain" />
        </div>
      )}

      {rejecting && (
        <div className="mt-3 space-y-2 rounded-xl border border-rose-200 bg-rose-50 p-3">
          <TextArea label="Why is it rejected? The applicant sees this." value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="For example: the photo is blurry, please upload a sharper one." rows={2} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="danger" busy={busy} disabled={reason.trim().length < 5} onClick={() => decide(false)}>Reject document</Button>
            <Button size="sm" variant="ghost" onClick={() => { setRejecting(false); setReason(""); }}>Cancel</Button>
          </div>
        </div>
      )}
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
    </li>
  );
}

function AccountDecision({ base, kind, status, userId, docs, reload }: {
  base: string; kind: "driver" | "laundry"; status: string; userId?: string; docs: DocumentsOverview | null; reload: () => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const waiting = docs?.requirements.filter((r) => r.status !== "approved").map((r) => r.name) ?? [];
  const ready = docs !== null && waiting.length === 0;
  const act = (fn: () => Promise<unknown>, message: string) => void run(async () => {
    await fn();
    setReason("");
    setDone(message);
    await reload();
  });

  return (
    <Card title="Decision">
      <div className="space-y-4">
        {status === "approved" ? (
          <Alert kind="success">This {kind} is approved and can work on the platform.</Alert>
        ) : ready ? (
          <Alert kind="success">All documents are approved. You can approve this {kind}.</Alert>
        ) : (
          <Alert kind="info" title="Can't approve yet">
            These documents still need to be approved: {waiting.join(", ")}.
          </Alert>
        )}
        {status !== "approved" && (
          <Button className="w-full" icon="check" busy={busy} disabled={!ready}
            onClick={() => act(() => api(`${base}/approve`, { method: "POST" }), `The ${kind} is approved and has been notified.`)}>
            Approve {kind}
          </Button>
        )}

        <div className="border-t border-slate-100 pt-4">
          <p className="text-sm font-medium text-slate-900">{status === "approved" ? "Revoke or suspend" : "Reject or suspend"}</p>
          <p className="mt-0.5 text-sm text-slate-500">Give a reason. The {kind} sees it.</p>
          <div className="mt-2 space-y-2">
            <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
            <div className="flex flex-wrap gap-2">
              {status !== "rejected" && (
                <Button variant="danger" size="sm" busy={busy} disabled={reason.trim().length < 5}
                  onClick={() => act(() => api(`${base}/reject`, { json: { reason } }), status === "approved" ? "Approval revoked." : `The ${kind} has been rejected.`)}>
                  {status === "approved" ? "Revoke approval" : `Reject ${kind}`}
                </Button>
              )}
              {userId && (
                <Button variant="secondary" size="sm" busy={busy} disabled={reason.trim().length < 5}
                  onClick={() => act(() => api(`/api/admin/users/${userId}/suspend`, { json: { reason } }), "The account is suspended.")}>
                  Suspend account
                </Button>
              )}
            </div>
          </div>
        </div>
        {done && <Alert kind="success">{done}</Alert>}
        <Alert>{error}</Alert>
      </div>
    </Card>
  );
}

function ReviewLayout({ title, status, registered, details, docs, decision }: {
  title: string; status: string; registered: string; details: [string, ReactNode][];
  docs: ReturnType<typeof useAsync<DocumentsOverview>>; decision: ReactNode;
}) {
  return (
    <div>
      <PageTitle back={{ to: "/admin", label: "Verification" }} sub={`Signed up ${when(registered)}`}
        actions={<StatusBadge status={status} />}>{title}</PageTitle>
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_22rem]">
        <div className="min-w-0">
          {docs.loading && !docs.data ? <Spinner /> : docs.data ? <DocumentReview overview={docs.data} reload={docs.reload} /> : <Alert>{docs.error}</Alert>}
        </div>
        <div className="space-y-5 lg:sticky lg:top-24">
          <Card title="Details"><KeyValue items={details} /></Card>
          {decision}
        </div>
      </div>
    </div>
  );
}

export function AdminDriver() {
  const { id } = useParams();
  const driver = useAsync(() => api<DriverReview>(`/api/admin/drivers/${id}`), [id]);
  const docs = useAsync(() => api<DocumentsOverview>(`/api/admin/drivers/${id}/documents`), [id]);
  if (driver.loading && !driver.data) return <Spinner />;
  if (!driver.data) return <Alert>{driver.error}</Alert>;
  const d = driver.data;
  const reload = async () => { await driver.reload(); await docs.reload(); };
  const details: [string, ReactNode][] = [
    ["Email", d.email], ["Phone", d.phone], ["ID / passport no.", d.id_number],
    ["Vehicle", d.vehicle_type ? [label(d.vehicle_type), d.vehicle_registration].filter(Boolean).join(" · ") : "None"],
  ];
  if (d.rejection_reason) details.push(["Last reason", d.rejection_reason]);
  return (
    <ReviewLayout title={d.full_name} status={d.verification_status} registered={d.registered_at} details={details} docs={docs}
      decision={<AccountDecision base={`/api/admin/drivers/${d.user_id}`} kind="driver" status={d.verification_status}
        userId={d.user_id} docs={docs.data} reload={reload} />} />
  );
}

export function AdminBusiness() {
  const { id } = useParams();
  const biz = useAsync(() => api<BusinessReview>(`/api/admin/businesses/${id}`), [id]);
  const docs = useAsync(() => api<DocumentsOverview>(`/api/admin/businesses/${id}/documents`), [id]);
  if (biz.loading && !biz.data) return <Spinner />;
  if (!biz.data) return <Alert>{biz.error}</Alert>;
  const b = biz.data;
  const reload = async () => { await biz.reload(); await docs.reload(); };
  const details: [string, ReactNode][] = [
    ["Owner", b.owner_name], ["Owner email", b.owner_email], ["CIPC number", b.registration_number],
    ["Address", [b.address_line, b.suburb, b.city].filter(Boolean).join(", ")], ["Phone", b.contact_phone],
  ];
  if (b.rejection_reason) details.push(["Last reason", b.rejection_reason]);
  return (
    <ReviewLayout title={b.business_name} status={b.verification_status} registered={b.registered_at} details={details} docs={docs}
      decision={<AccountDecision base={`/api/admin/businesses/${b.id}`} kind="laundry" status={b.verification_status}
        docs={docs.data} reload={reload} />} />
  );
}

// ---------- Incidents (SEC-036, SEC-037, UAT-013) ----------

export function AdminIncidents() {
  const [status, setStatus] = useState("active");
  const { data, loading, error } = useAsync(() => {
    const q = status === "active" ? "" : `?status=${status}`;
    return api<Page<IncidentSummary>>(`/api/admin/incidents${q}`);
  }, [status]);
  return (
    <div className="space-y-4">
      <PageTitle sub="Reports from users and problems the system detected by itself."
        actions={<div className="w-52"><Select aria-label="Show" value={status} onChange={(e) => setStatus(e.target.value)} options={[
          { value: "active", label: "Open & investigating" }, ...["open", "investigating", "resolved", "dismissed"].map((s) => ({ value: s, label: label(s) }))]} /></div>}>
        Incidents
      </PageTitle>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? <Card><Empty icon="checkCircle" title="All clear">No incidents here.</Empty></Card> : (
        <Card padded={false}>
          <ul className="divide-y divide-slate-100">
            {data.items.map((i) => (
              <li key={i.id}>
                <ListRow to={`/admin/incidents/${i.id}`}>
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 font-mono text-sm font-semibold text-slate-900">{i.reference} {i.is_automatic && <Badge color="purple">automatic</Badge>}</p>
                    <p className="text-sm text-slate-500">{label(i.category)}{i.order_number && ` · order ${i.order_number}`}</p>
                  </div>
                  <span className="flex gap-2"><StatusBadge status={i.severity} /><StatusBadge status={i.status} /></span>
                </ListRow>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

const NEXT: Record<string, string[]> = {
  open: ["investigating", "dismissed"], investigating: ["resolved", "dismissed"],
  resolved: ["investigating"], dismissed: ["investigating"],
};

export function AdminIncidentDetail() {
  const { id } = useParams();
  const { data, loading, error, setData } = useAsync(() => api<AdminIncident>(`/api/admin/incidents/${id}`), [id]);
  const [note, setNote] = useState("");
  const [internal, setInternal] = useState(true);
  const [resolution, setResolution] = useState("");
  const { busy, error: actionError, run } = useAction();
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const ev = data.evidence;
  const photos = [...(ev?.photos ?? []), ...data.incident_photos.filter((p) => !ev?.photos.some((q) => q.id === p.id))];

  const status = (to: string) => void run(async () => {
    setData(await api<AdminIncident>(`/api/admin/incidents/${data.id}/status`, { json: { status: to, note: note || null, resolution: resolution || null } }));
    setNote(""); setResolution("");
  });

  return (
    <div className="space-y-4">
      <PageTitle back={{ to: "/admin/incidents", label: "Incidents" }} actions={<><StatusBadge status={data.severity} /><StatusBadge status={data.status} /></>}
        sub={<>{label(data.category)} · reported by {data.reporter_name} ({data.reporter_role}) · {when(data.created_at)}</>}>
        <span className="font-mono">{data.reference}</span>
      </PageTitle>
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Card title="Report"><p className="whitespace-pre-wrap text-sm">{data.description}</p></Card>
          {ev && (
            <>
              <Card title={`Order ${ev.order_number}`}>
                <KeyValue items={[["Status", <StatusBadge key="s" status={ev.order_status} />], ["Laundry", ev.business_name], ["Customer", ev.customer_name]]} />
              </Card>
              <Card title="Handovers (who, when, where)">
                {!ev.handovers.length ? <Empty>None.</Empty> : (
                  <ul className="space-y-2 text-sm">
                    {ev.handovers.map((h, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2">
                        <b>{label(h.kind)}</b> {h.from_name} → {h.to_name} · {h.method} · {when(h.created_at)}
                        {h.latitude != null && <a className="text-brand-700 underline" target="_blank" rel="noreferrer" href={osmLink(h.latitude, h.longitude!)}>location</a>}
                        {h.location_flagged && <Badge color="red">{Math.round(h.distance_from_expected_m ?? 0)} m from address</Badge>}
                      </li>
                    ))}
                  </ul>
                )}
                {ev && <Link to={`/admin/routes?order=${data.order_id}`} className="mt-2 inline-block text-sm text-brand-700 underline">Driver routes for this order</Link>}
              </Card>
              <Card title="Seals"><Seals items={ev.seals} /></Card>
              <Card title="Status history"><Timeline events={ev.history} /></Card>
            </>
          )}
          <Card title={`Photos (${photos.length})`}>
            {!photos.length ? <Empty>No photos.</Empty> : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {photos.map((p) => (
                  <figure key={p.id} className="text-xs text-slate-500">
                    <AuthImage path={`/api/photos/${p.id}/file`} alt={p.caption ?? p.stage} className="h-32 w-full rounded-lg object-cover" />
                    <figcaption>{label(p.stage)} · {p.uploader_role}</figcaption>
                  </figure>
                ))}
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Investigation">
            <div className="space-y-3">
              <Select label="Severity" value={data.severity} onChange={(e) => void run(async () => setData(await api<AdminIncident>(`/api/admin/incidents/${data.id}`, { method: "PATCH", json: { severity: e.target.value } })))}
                options={["low", "medium", "high", "critical"].map((s) => ({ value: s, label: label(s) }))} />
              <TextArea label="Note" value={note} onChange={(e) => setNote(e.target.value)} />
              <Checkbox checked={internal} onChange={(e) => setInternal(e.target.checked)} label="Internal note (hidden from the reporter)" />
              <Button variant="secondary" busy={busy} disabled={!note} onClick={() => void run(async () => {
                setData(await api<AdminIncident>(`/api/admin/incidents/${data.id}/comments`, { json: { note, internal } })); setNote("");
              })}>Add note</Button>
              {NEXT[data.status].some((s) => s === "resolved" || s === "dismissed") && (
                <TextArea label="Outcome (needed to close)" value={resolution} onChange={(e) => setResolution(e.target.value)} />
              )}
              <div className="flex flex-wrap gap-2">
                {NEXT[data.status].map((s) => <Button key={s} busy={busy} variant={s === "dismissed" ? "ghost" : "primary"} onClick={() => status(s)}>{s === "investigating" && data.status !== "open" ? "Reopen" : label(s)}</Button>)}
              </div>
              <Alert>{actionError}</Alert>
              <p className="text-xs text-slate-500">To suspend a driver or laundry involved, open their profile from Verification.</p>
            </div>
          </Card>
          <Card title="Trail">
            <ul className="space-y-2 text-sm">
              {data.updates.map((u, i) => (
                <li key={i} className={u.internal ? "rounded-lg bg-amber-50 p-2" : ""}>
                  <span className="text-slate-500">{when(u.created_at)} · {u.author}</span>{u.internal && <Badge color="amber">internal</Badge>}
                  {u.to_status && <> · <StatusBadge status={u.to_status} /></>}
                  {u.note && <p>{u.note}</p>}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------- Route deviations (SEC-023, SEC-024) ----------

interface Deviation { job_id: string; order_id: string; order_number: string; kind: string; driver_name: string | null; off_route_points: number; first_seen: string }
interface JobRoute { job_id: string; kind: string; driver_name: string | null; off_route_points: number;
  points: { latitude: number; longitude: number; off_route: boolean; recorded_at: string }[] }

export function RouteAlerts() {
  const params = new URLSearchParams(window.location.search);
  const [orderId, setOrderId] = useState(params.get("order"));
  const list = useAsync(() => api<Deviation[]>("/api/admin/route-deviations"));
  const route = useAsync(() => orderId ? api<JobRoute[]>(`/api/admin/orders/${orderId}/route`) : Promise.resolve(null), [orderId]);
  return (
    <div className="space-y-4">
      <PageTitle sub="Trips where a driver carrying laundry went well off the direct route.">Route alerts</PageTitle>
      <Card>
        {list.loading ? <Spinner /> : !list.data?.length ? <Empty>No deviations recorded.</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {list.data.map((d) => (
              <li key={d.job_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span><span className="font-mono">{d.order_number}</span> · {d.kind} · {d.driver_name} · {d.off_route_points} off-route point(s) · first {when(d.first_seen)}</span>
                <Button variant="ghost" onClick={() => setOrderId(d.order_id)}>Show route</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {route.data && (
        <Card title="Recorded route">
          {route.data.map((r) => (
            <div key={r.job_id} className="mb-3">
              <p className="text-sm font-medium">{label(r.kind)} · {r.driver_name} · {r.points.length} point(s)</p>
              {r.points.length > 0 && (
                <div className="my-2">
                  <MapView height={280}
                    line={r.points.map((p) => [p.latitude, p.longitude] as [number, number])}
                    highlight={r.points.filter((p) => p.off_route).map((p) => [p.latitude, p.longitude] as [number, number])}
                    points={[
                      { latitude: r.points[0].latitude, longitude: r.points[0].longitude, label: "First position", color: "green" },
                      { latitude: r.points[r.points.length - 1].latitude, longitude: r.points[r.points.length - 1].longitude, label: "Last position", color: "grey" },
                    ]} />
                  <p className="mt-1 text-xs text-slate-500">Red dots: positions while carrying laundry that were well off the direct route.</p>
                </div>
              )}
              <ul className="mt-1 max-h-60 overflow-auto text-xs">
                {r.points.map((p, i) => (
                  <li key={i} className={p.off_route ? "text-rose-700" : "text-slate-600"}>
                    {when(p.recorded_at)} · <a className="underline" target="_blank" rel="noreferrer" href={osmLink(p.latitude, p.longitude)}>{p.latitude.toFixed(5)}, {p.longitude.toFixed(5)}</a>
                    {p.off_route && " · off route"}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
