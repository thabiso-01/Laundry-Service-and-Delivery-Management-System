import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, apiBlobUrl } from "../api/client";
import type { Doc, DocumentsOverview, Incident, IncidentSummary, Notification, OrderSummary, Page, Requirement } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, ButtonLink, Card, Checkbox, Empty, Input, ListRow, PageTitle, Select, Spinner, StatusBadge, TextArea } from "../components/ui";
import { Icon, type IconName } from "../components/icons";
import { SelfieCamera } from "../components/SelfieCamera";
import { label, when } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";

// ---------- Verification documents (SEC-001, SEC-002, SEC-043) ----------

const MAX_BYTES = 5 * 1024 * 1024;

// What to upload for each document, in plain words
const DOC_INFO: Record<string, { icon: IconName; hint: string; selfie?: boolean }> = {
  national_id: { icon: "file", hint: "A clear photo or scan of your SA ID card or ID book, with every corner visible." },
  passport: { icon: "file", hint: "A clear photo or scan of your passport's photo page." },
  selfie: { icon: "camera", hint: "A photo of your face, taken now, so we can match it to your ID. No sunglasses or hat.", selfie: true },
  profile_photo: { icon: "user", hint: "Customers see this photo when you collect their laundry. Your face must be clearly visible." },
  drivers_licence: { icon: "truck", hint: "The front of your driver's licence card, with every corner visible." },
  vehicle_registration: { icon: "truck", hint: "Your vehicle's registration document." },
  business_registration: { icon: "store", hint: "Your CIPC registration certificate." },
  proof_of_address: { icon: "pin", hint: "A recent utility bill or lease showing the shop's address." },
  tax_clearance: { icon: "file", hint: "Your SARS tax clearance certificate." },
};
const TYPE_NAME: Record<string, string> = { national_id: "SA ID", passport: "Passport" };

const STATE: Record<Requirement["status"], { text: string; tone: string; icon: IconName }> = {
  missing: { text: "Not uploaded yet", tone: "bg-slate-100 text-slate-600", icon: "upload" },
  pending: { text: "Uploaded, waiting for review", tone: "bg-amber-50 text-amber-700", icon: "clock" },
  approved: { text: "Approved", tone: "bg-emerald-50 text-emerald-700", icon: "check" },
  rejected: { text: "Not accepted, please upload a new one", tone: "bg-rose-50 text-rose-700", icon: "x" },
};

const BAR: Record<Requirement["status"], string> = {
  missing: "bg-slate-200", pending: "bg-amber-400", approved: "bg-emerald-500", rejected: "bg-rose-500",
};

export function Documents() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api<DocumentsOverview>("/api/documents"));

  if (loading && !data) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const reqs = data.requirements;
  const approved = reqs.filter((r) => r.status === "approved").length;
  const uploaded = reqs.filter((r) => r.status !== "missing").length;
  const driver = me?.role === "driver";

  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle sub={driver ? "We check who you are before you can take jobs." : "We verify every laundry before it can receive orders."}>
        Verification documents
      </PageTitle>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-slate-900">
            {data.all_approved ? "You're verified" : data.ready_for_review ? "Everything is uploaded" : `${uploaded} of ${reqs.length} uploaded`}
          </p>
          <p className="text-sm text-slate-500">{approved} of {reqs.length} approved</p>
        </div>
        <div className="mt-3 flex gap-1.5">
          {reqs.map((r) => <span key={r.name} className={`h-2 flex-1 rounded-full ${BAR[r.status]}`} />)}
        </div>
        <p className="mt-3 text-sm text-slate-600">
          {data.all_approved ? "All your documents are approved."
            : data.ready_for_review ? "We'll review your documents and send you a notification."
            : "Upload each document below: a photo (JPEG or PNG) or a PDF, up to 5 MB."}
        </p>
      </Card>

      <ul className="stagger space-y-3">
        {reqs.map((r) => <RequirementCard key={r.name} req={r} docs={data.documents} onDone={reload} />)}
      </ul>

      {data.documents.length > 0 && (
        <details className="group rounded-2xl border border-slate-100 bg-surface shadow-card">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3.5 text-sm font-medium text-slate-700 sm:px-5">
            All uploads ({data.documents.length})
            <Icon name="chevronRight" className="h-4 w-4 text-slate-400 transition group-open:rotate-90" />
          </summary>
          <ul className="divide-y divide-slate-100 border-t border-slate-100 px-4 sm:px-5">
            {data.documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-slate-800">{TYPE_NAME[d.document_type] ?? label(d.document_type)}</p>
                  <p className="truncate text-xs text-slate-500">{d.original_filename} · {when(d.uploaded_at)}</p>
                </div>
                <span className="flex items-center gap-3">
                  <ViewLink id={d.id} />
                  <StatusBadge status={d.status} />
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ViewLink({ id }: { id: string }) {
  return (
    <button type="button" className="text-sm font-medium text-brand-700 hover:underline"
      onClick={async () => window.open(await apiBlobUrl(`/api/documents/${id}/file`), "_blank")}>
      View
    </button>
  );
}

function RequirementCard({ req, docs, onDone }: { req: Requirement; docs: Doc[]; onDone: () => Promise<void> }) {
  const { busy, error, setError, run } = useAction();
  const [type, setType] = useState(req.accepted_types[0]);
  const [camera, setCamera] = useState(false);
  const current = docs.find((d) => d.id === req.document_id) ?? null;
  const info = DOC_INFO[current?.document_type ?? type] ?? { icon: "file" as IconName, hint: "" };
  const state = STATE[req.status];
  const canUpload = req.status !== "approved";
  const inputId = `doc-${req.accepted_types.join("-")}`;

  const pick = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("That file is bigger than 5 MB. Take a smaller photo or compress the PDF.");
      return;
    }
    void run(async () => {
      const form = new FormData();
      form.set("document_type", type);
      form.set("file", file);
      await api("/api/documents", { form });
      await onDone();
    });
  };

  return (
    <li className="rounded-2xl border border-slate-100 bg-surface p-4 shadow-card sm:p-5">
      <div className="flex gap-3.5">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700">
          <Icon name={info.icon} className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-slate-900">{req.name}</p>
          <span className={`mt-1 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${state.tone}`}>
            <Icon name={state.icon} className="h-3.5 w-3.5" /> {state.text}
          </span>
          {req.status === "rejected" && req.notes && <p className="mt-2 text-sm text-rose-700">Reason: {req.notes}</p>}
          {canUpload && info.hint && <p className="mt-2 text-sm text-slate-600">{info.hint}</p>}
          {current && (
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <Icon name="file" className="h-4 w-4 shrink-0" />
                <span className="truncate">{current.original_filename}</span>
              </span>
              <ViewLink id={current.id} />
            </p>
          )}
        </div>
      </div>

      {canUpload && (
        <div className="mt-4 flex flex-wrap items-center gap-2 sm:pl-[3.6rem]">
          {req.accepted_types.length > 1 && (
            <div role="radiogroup" aria-label="Document type" className="inline-flex rounded-full bg-slate-100 p-1">
              {req.accepted_types.map((t) => (
                <button key={t} type="button" role="radio" aria-checked={type === t} onClick={() => setType(t)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium ${type === t ? "bg-surface text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>
                  {TYPE_NAME[t] ?? label(t)}
                </button>
              ))}
            </div>
          )}
          {info.selfie ? (
            // Selfies are taken live with the camera; no file upload
            <Button icon={busy ? "clock" : "camera"} variant={current ? "secondary" : "primary"} busy={busy} onClick={() => setCamera(true)}>
              {busy ? "Uploading…" : current ? "Take a new selfie" : "Take selfie"}
            </Button>
          ) : (
            <>
              <label htmlFor={inputId}
                className={`inline-flex h-10 cursor-pointer items-center gap-2 rounded-xl px-4 text-sm font-medium shadow-sm ${current ? "border border-slate-200 bg-surface text-slate-800 hover:bg-slate-50" : "bg-brand-600 text-white shadow-brand-600/25 hover:bg-deep"} ${busy ? "pointer-events-none opacity-60" : ""}`}>
                <Icon name={busy ? "clock" : "upload"} className="h-4 w-4" />
                {busy ? "Uploading…" : current ? "Upload a new one" : "Upload file"}
              </label>
              <input id={inputId} type="file" className="sr-only" disabled={busy}
                accept="image/jpeg,image/png,application/pdf"
                onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
            </>
          )}
        </div>
      )}
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      {camera && <SelfieCamera onClose={() => setCamera(false)} onUse={(photo) => { setCamera(false); pick(photo); }} />}
    </li>
  );
}

// ---------- Notifications (UR-016) ----------

export function Notifications() {
  const navigate = useNavigate();
  const { me } = useAuth();
  const { data, loading, error, reload } = useAsync(() => api<{ items: Notification[]; unread: number }>("/api/notifications?limit=100"));
  const open = async (n: Notification) => {
    if (!n.read_at) await api(`/api/notifications/${n.id}/read`, { method: "POST" });
    if (n.order_id) {
      const base = me?.role === "business" ? "/business/orders" : me?.role === "customer" ? "/orders" : null;
      if (base) return navigate(`${base}/${n.order_id}`);
    }
    if (n.incident_id) return navigate(me?.role === "admin" ? `/admin/incidents/${n.incident_id}` : `/incidents/${n.incident_id}`);
    await reload();
  };
  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between">
        <PageTitle>Notifications</PageTitle>
        {Boolean(data?.unread) && <Button variant="ghost" onClick={async () => { await api("/api/notifications/read-all", { method: "POST" }); await reload(); }}>Mark all read</Button>}
      </div>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? <Empty>Nothing yet.</Empty> : (
        <ul className="space-y-2">
          {data.items.map((n) => (
            <li key={n.id}>
              <button onClick={() => void open(n)} className={`w-full rounded-xl border p-3 text-left ${n.read_at ? "border-slate-200 bg-surface" : "border-brand-200 bg-brand-50"}`}>
                <p className="font-medium">{n.title}</p>
                <p className="text-sm text-slate-700">{n.body}</p>
                <p className="mt-1 text-xs text-slate-500">{when(n.created_at)}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------- My reports (UR-015, SEC-033/034/048) ----------

const CATS = ["missing_items", "damaged_items", "wrong_items", "broken_seal", "seal_mismatch",
  "late_or_no_show", "conduct", "fraud", "security", "other"];

export function MyIncidents() {
  const { data, loading, error } = useAsync(() => api<Page<IncidentSummary>>("/api/incidents?limit=50"));
  return (
    <div className="max-w-3xl">
      <PageTitle sub="Something wrong with an order, a driver or a laundry? Tell us and track what we do about it."
        actions={<ButtonLink to="/incidents/new" icon="plus">Report a problem</ButtonLink>}>Help & reports</PageTitle>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
        <Card><Empty icon="flag" title="No reports">You haven't reported anything. If something goes wrong, we're here to help.</Empty></Card>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-slate-100">
            {data.items.map((i) => (
              <li key={i.id}>
                <ListRow to={`/incidents/${i.id}`}>
                  <div className="min-w-0">
                    <p className="font-mono text-sm font-semibold text-slate-900">{i.reference}</p>
                    <p className="text-sm text-slate-500">{label(i.category)}{i.order_number && ` · order ${i.order_number}`}</p>
                  </div>
                  <StatusBadge status={i.status} />
                </ListRow>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function NewIncident() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const orders = useAsync(() => me?.role === "customer" ? api<Page<OrderSummary>>("/api/orders?limit=50") : Promise.resolve(null), [me?.role]);
  const [orderId, setOrderId] = useState(params.get("order") ?? "");
  const [category, setCategory] = useState("missing_items");
  const [description, setDescription] = useState("");
  const { busy, error, run } = useAction();

  const orderOptions = [{ value: "", label: "Not about a specific order" },
    ...(orders.data?.items ?? []).map((o) => ({ value: o.id, label: `${o.order_number} · ${o.business_name}` }))];
  if (orderId && !orderOptions.some((o) => o.value === orderId)) orderOptions.push({ value: orderId, label: "This order" });

  return (
    <div className="max-w-xl">
      <PageTitle sub="You'll get a reference number to quote. Our team investigates every report.">Report a problem</PageTitle>
      <Card>
        <div className="space-y-3">
          <Select label="Which order?" value={orderId} onChange={(e) => setOrderId(e.target.value)} options={orderOptions} />
          <Select label="What happened?" value={category} onChange={(e) => setCategory(e.target.value)} options={CATS.map((c) => ({ value: c, label: label(c) }))} />
          <TextArea label="Details" value={description} onChange={(e) => setDescription(e.target.value)} rows={5}
            placeholder="Which items, what you noticed, and when." />
          <Alert>{error}</Alert>
          <Button busy={busy} disabled={description.length < 10} onClick={() => void run(async () => {
            const inc = await api<Incident>("/api/incidents", { json: { order_id: orderId || null, category, description } });
            navigate(`/incidents/${inc.id}`);
          })}>Send report</Button>
        </div>
      </Card>
    </div>
  );
}

export function IncidentDetail() {
  const { id } = useParams();
  const { data, loading, error, reload } = useAsync(() => api<Incident>(`/api/incidents/${id}`), [id]);
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const { busy, error: actionError, run } = useAction();
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const closed = ["resolved", "dismissed"].includes(data.status);
  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle back={{ to: "/incidents", label: "Help & reports" }} actions={<StatusBadge status={data.status} />}
        sub={<>{label(data.category)} {data.order_number && `· order ${data.order_number}`}</>}>
        <span className="font-mono">{data.reference}</span>
      </PageTitle>
      <Card title="Your report"><p className="whitespace-pre-wrap text-sm">{data.description}</p></Card>
      {data.resolution && <Alert kind="success"><b>Outcome:</b> {data.resolution}</Alert>}
      <Card title="Updates">
        <ul className="space-y-3 text-sm">
          {data.updates.map((u, i) => (
            <li key={i}><span className="text-slate-500">{when(u.created_at)} · {u.author}</span>
              {u.to_status && <> · <StatusBadge status={u.to_status} /></>}
              {u.note && <p className="mt-0.5 text-slate-800">{u.note}</p>}</li>
          ))}
        </ul>
      </Card>
      {!closed && (
        <Card title="Add information">
          <div className="space-y-3">
            <TextArea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Anything else we should know?" />
            <Button variant="secondary" busy={busy} disabled={!note} onClick={() => void run(async () => {
              await api(`/api/incidents/${data.id}/comments`, { json: { note } }); setNote(""); await reload();
            })}>Add</Button>
            <div className="border-t border-slate-100 pt-3">
              <Input label="Attach a photo (JPEG or PNG)" type="file" accept="image/jpeg,image/png" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
              <Button className="mt-2" variant="secondary" busy={busy} disabled={!photo} onClick={() => void run(async () => {
                const form = new FormData();
                form.set("stage", "incident"); form.set("incident_id", data.id); form.set("file", photo!);
                await api("/api/photos", { form }); setPhoto(null); await reload();
              })}>Upload photo</Button>
            </div>
            <Alert>{actionError}</Alert>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------- Account security: two-step login (SEC-039) ----------

export function Security() {
  const { me, refresh } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const { busy, error, run } = useAction();
  if (!me) return <Spinner />;
  return (
    <div className="max-w-xl space-y-4">
      <PageTitle sub={`${me.full_name} · ${me.email}`}>Account & privacy</PageTitle>
      <Card title="Two-step login">
        {codes ? (
          <div className="space-y-2">
            <Alert kind="success">Two-step login is on.</Alert>
            <p className="text-sm">Save these recovery codes somewhere safe. Each works once if you lose your phone. They won't be shown again.</p>
            <ul className="grid grid-cols-2 gap-1 font-mono text-sm">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
        ) : me.mfa_enabled ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">On. Signing in asks for a code from your authenticator app.</p>
            <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Input label="Code from your app" value={code} onChange={(e) => setCode(e.target.value)} />
            <Button variant="danger" busy={busy} onClick={() => void run(async () => {
              await api("/api/auth/mfa/disable", { json: { password, code } }); setCode(""); setPassword(""); await refresh();
            })}>Turn off</Button>
          </div>
        ) : setup ? (
          <div className="space-y-3">
            <p className="text-sm">Add this key to Google Authenticator, Microsoft Authenticator or Authy (choose "enter a setup key"):</p>
            <p className="break-all rounded-lg bg-slate-100 p-2 font-mono text-sm">{setup.secret}</p>
            <Input label="Enter the 6-digit code it shows" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
            <Button busy={busy} disabled={code.length !== 6} onClick={() => void run(async () => {
              const out = await api<{ recovery_codes: string[] }>("/api/auth/mfa/enable", { json: { code } });
              setCodes(out.recovery_codes); setCode(""); await refresh();
            })}>Turn on</Button>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">Protect your account with a code from your phone in addition to your password.</p>
            <Button busy={busy} onClick={() => void run(async () => setSetup(await api("/api/auth/mfa/setup", { method: "POST" })))}>Set up</Button>
          </div>
        )}
        <div className="mt-3"><Alert>{error}</Alert></div>
      </Card>
      <Card title="Password"><Link to="/change-password" className="text-sm text-brand-700 underline">Change your password</Link></Card>
      <PrivacyCards />
    </div>
  );
}

function SmsCard() {
  const { me, refresh } = useAuth();
  const { busy, error, run } = useAction();
  if (!me) return null;
  return (
    <Card title="Text messages (SMS)">
      <p className="mb-3 text-sm text-slate-600">
        {me.phone
          ? <>We text <b>{me.phone}</b> only for important moments: your driver is on the way, your laundry is out for
            delivery or delivered, a balance to pay, and security alerts. Everything also appears in your notifications.</>
          : <>Add a mobile number to your account to get important updates by SMS.</>}
      </p>
      <Checkbox checked={me.sms_enabled} disabled={busy || !me.phone}
        onChange={(e) => void run(async () => {
          await api("/api/me/preferences", { method: "PATCH", json: { sms_enabled: e.target.checked } });
          await refresh();
        })}
        label="Send me important updates by SMS" />
      <div className="mt-2"><Alert>{error}</Alert></div>
    </Card>
  );
}

// POPIA s23 (access) and s24 (deletion)
function PrivacyCards() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [confirm, setConfirm] = useState("");
  const download = useAction();
  const removal = useAction();
  if (!me) return null;

  const getData = () => void download.run(async () => {
    const url = await apiBlobUrl("/api/me/data-export");
    const a = document.createElement("a");
    a.href = url;
    a.download = `laundryconnect-my-data-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  const remove = () => void removal.run(async () => {
    await api("/api/me", { method: "DELETE", json: { password, code: code || null, confirm } });
    logout();
    navigate("/?deleted=1", { replace: true });
  });

  return (
    <>
      <SmsCard />
      <Card title="Your data">
        <p className="mb-3 text-sm text-slate-600">
          Download a copy of everything LaundryConnect holds about you: your account, addresses, orders,
          payments, reports, notifications and sign-in history (POPIA section 23).
        </p>
        <Alert>{download.error}</Alert>
        <Button variant="secondary" busy={download.busy} onClick={getData}>Download my data</Button>
      </Card>

      {me.role !== "admin" && (
        <Card title="Delete account">
          <div className="space-y-3 text-sm">
            <p className="text-slate-600">This can't be undone. We remove your name, contact details, password, home
              address, ID documents, notifications, review comments and location history.</p>
            <p className="text-slate-600">The law requires us to keep some records, stripped of your details:</p>
            <ul className="list-disc space-y-1 pl-5 text-slate-600">
              <li>orders and payments (amounts, dates and suburb) for tax purposes, for 5 years;</li>
              <li>handover, seal and photo records, and reports you made, in case of a dispute;</li>
              <li>our security log, linked only to an anonymous account number.</li>
            </ul>
            <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {me.mfa_enabled && <Input label="Code from your authenticator app" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />}
            <Input label='Type DELETE to confirm' value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <Alert>{removal.error}</Alert>
            <Button variant="danger" busy={removal.busy} disabled={confirm !== "DELETE" || !password} onClick={remove}>
              Delete my account permanently
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}
