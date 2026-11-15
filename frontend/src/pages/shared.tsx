import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, apiBlobUrl } from "../api/client";
import type { DocumentsOverview, Incident, IncidentSummary, Notification, OrderSummary, Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Alert, Button, Card, Checkbox, Empty, Input, PageTitle, Select, Spinner, StatusBadge, TextArea } from "../components/ui";
import { label, when } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";

// ---------- Verification documents (SEC-001, SEC-002, SEC-043) ----------

export function Documents() {
  const { me } = useAuth();
  const { data, error, loading, reload } = useAsync(() => api<DocumentsOverview>("/api/documents"));
  const [type, setType] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const { busy, error: upError, run } = useAction();

  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const types = Array.from(new Set(data.requirements.flatMap((r) => r.accepted_types)));
  const chosen = type || types[0];

  const upload = () => void run(async () => {
    const form = new FormData();
    form.set("document_type", chosen);
    form.set("file", file!);
    await api("/api/documents", { form });
    setFile(null);
    await reload();
  });

  return (
    <div className="max-w-3xl space-y-4">
      <PageTitle sub={me?.role === "driver" ? "We check your identity before you can take jobs." : "We verify every laundry before it can receive orders."}>Verification documents</PageTitle>
      {data.all_approved ? <Alert kind="success">All required documents are approved.</Alert>
        : data.ready_for_review ? <Alert kind="info">Everything is uploaded. We'll review it shortly.</Alert> : null}
      <Card title="What we need">
        <ul className="divide-y divide-slate-100">
          {data.requirements.map((r) => (
            <li key={r.name} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <div><p className="font-medium">{r.name}</p>{r.notes && <p className="text-xs text-rose-700">{r.notes}</p>}</div>
              <StatusBadge status={r.status} />
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Upload a document">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Document" value={chosen} onChange={(e) => setType(e.target.value)} options={types.map((t) => ({ value: t, label: label(t) }))} />
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-700">File (JPEG, PNG or PDF, max 5 MB)</span>
            <input type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
          </label>
        </div>
        <div className="mt-3 space-y-2"><Alert>{upError}</Alert><Button busy={busy} disabled={!file} onClick={upload}>Upload</Button></div>
      </Card>
      {data.documents.length > 0 && (
        <Card title="Uploaded">
          <ul className="divide-y divide-slate-100 text-sm">
            {data.documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>{label(d.document_type)} · {d.original_filename} · {when(d.uploaded_at)}</span>
                <span className="flex items-center gap-2">
                  <button className="text-sky-700 underline" onClick={async () => window.open(await apiBlobUrl(`/api/documents/${d.id}/file`), "_blank")}>View</button>
                  <StatusBadge status={d.status} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
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
              <button onClick={() => void open(n)} className={`w-full rounded-xl border p-3 text-left ${n.read_at ? "border-slate-200 bg-white" : "border-sky-200 bg-sky-50"}`}>
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
      <div className="flex items-center justify-between">
        <PageTitle>My reports</PageTitle>
        <Link to="/incidents/new"><Button>Report a problem</Button></Link>
      </div>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? <Empty>You haven't reported anything.</Empty> : (
        <ul className="space-y-2">
          {data.items.map((i) => (
            <li key={i.id}>
              <Link to={`/incidents/${i.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3 hover:border-sky-300">
                <span><span className="font-mono font-semibold">{i.reference}</span> · {label(i.category)} {i.order_number && `· ${i.order_number}`}</span>
                <StatusBadge status={i.status} />
              </Link>
            </li>
          ))}
        </ul>
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
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-2xl font-bold">{data.reference}</h1>
        <StatusBadge status={data.status} />
        <span className="text-sm text-slate-500">{label(data.category)} {data.order_number && `· order ${data.order_number}`}</span>
      </div>
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
      <Card title="Password"><Link to="/change-password" className="text-sm text-sky-700 underline">Change your password</Link></Card>
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
