import { useState } from "react";
import { api } from "../../api/client";
import type { Service } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { AddressPicker, type AddressValue } from "../../components/AddressPicker";
import { Alert, Badge, Button, Card, Empty, Input, PageTitle, Select, Spinner, StatusBadge, TextArea } from "../../components/ui";
import { CATEGORIES, label, rands, when } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";

// ---------- Services & prices (UR-006, Business Rule 11) ----------

const EMPTY = { name: "", category: "wash_and_fold", pricing_unit: "per_kg", price: "", min_quantity: "1", turnaround_hours: "48" };

export function Services() {
  const { me } = useAuth();
  const canEdit = me?.business?.staff_role !== "attendant";
  const { data, error, loading, reload } = useAsync(() => api<Service[]>("/api/business/services?include_inactive=true"));
  const [f, setF] = useState(EMPTY);
  const [prices, setPrices] = useState<Record<string, string>>({});
  const { busy, error: actionError, run } = useAction();

  const add = () => void run(async () => {
    await api("/api/business/services", { json: {
      name: f.name, category: f.category, pricing_unit: f.pricing_unit,
      price_cents: Math.round(Number(f.price) * 100), min_quantity: Number(f.min_quantity), turnaround_hours: Number(f.turnaround_hours),
    } });
    setF(EMPTY);
    await reload();
  });
  const patch = (id: string, body: unknown) => void run(async () => { await api(`/api/business/services/${id}`, { method: "PATCH", json: body }); await reload(); });

  return (
    <div>
      <PageTitle sub="Prices are fixed on each order when it's placed. Changes apply to new orders only.">Services & prices</PageTitle>
      <Alert>{actionError}</Alert>
      {canEdit && (
        <Card title="Add a service" className="mb-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Input label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Wash & fold" />
            <Select label="Category" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} options={CATEGORIES.map((c) => ({ value: c, label: label(c) }))} />
            <Select label="Priced" value={f.pricing_unit} onChange={(e) => setF({ ...f, pricing_unit: e.target.value })}
              options={[{ value: "per_kg", label: "Per kg" }, { value: "per_item", label: "Per item" }, { value: "per_load", label: "Per load" }]} />
            <Input label="Price (R)" type="number" min="0.01" step="0.01" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} />
            <Input label="Minimum quantity" type="number" min="1" value={f.min_quantity} onChange={(e) => setF({ ...f, min_quantity: e.target.value })} />
            <Input label="Ready in (hours)" type="number" min="1" max="720" value={f.turnaround_hours} onChange={(e) => setF({ ...f, turnaround_hours: e.target.value })} />
          </div>
          <Button className="mt-3" busy={busy} disabled={!f.name || !f.price} onClick={add}>Add service</Button>
        </Card>
      )}
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.length ? <Empty>No services yet.</Empty> : (
        <Card>
          <ul className="divide-y divide-slate-100">
            {data.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium">{s.name} {!s.is_active && <Badge>hidden</Badge>}</p>
                  <p className="text-xs text-slate-500">{label(s.category)} · {s.price_display} · ready in {s.turnaround_hours} h</p>
                </div>
                {canEdit && (
                  <div className="flex items-center gap-2">
                    <input type="number" step="0.01" min="0.01" aria-label="New price" className="w-24 rounded-lg border border-slate-300 px-2 py-1 text-sm"
                      placeholder={(s.price_cents / 100).toFixed(2)} value={prices[s.id] ?? ""} onChange={(e) => setPrices({ ...prices, [s.id]: e.target.value })} />
                    <Button variant="secondary" disabled={!prices[s.id]} onClick={() => patch(s.id, { price_cents: Math.round(Number(prices[s.id]) * 100) })}>Update price</Button>
                    <Button variant="ghost" onClick={() => patch(s.id, { is_active: !s.is_active })}>{s.is_active ? "Hide" : "Show"}</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

// ---------- Staff (SEC-011, SEC-017) ----------

interface StaffMember { id: string; full_name: string; email: string; staff_role: string; is_active: boolean; must_change_password: boolean; last_login_at: string | null }

export function Staff() {
  const { me } = useAuth();
  const isOwner = me?.business?.staff_role === "owner";
  const { data, error, loading, reload } = useAsync(() => api<StaffMember[]>("/api/business/staff"));
  const [f, setF] = useState({ full_name: "", email: "", phone: "", staff_role: "attendant" });
  const [secret, setSecret] = useState<string | null>(null);
  const { busy, error: actionError, run } = useAction();

  const add = () => void run(async () => {
    const out = await api<{ full_name: string; temporary_password: string }>("/api/business/staff", { json: { ...f, phone: f.phone || null } });
    setSecret(`${out.full_name}'s temporary password: ${out.temporary_password}`);
    setF({ full_name: "", email: "", phone: "", staff_role: "attendant" });
    await reload();
  });

  return (
    <div>
      <PageTitle sub="Everyone who handles laundry gets their own login, so every handover shows who did it.">Staff</PageTitle>
      {secret && <div className="mb-4"><Alert kind="success">{secret} — give it to them in person. It's shown only once; they choose their own password at first login.</Alert></div>}
      <Alert>{actionError}</Alert>
      <Card title="Add a staff member" className="mb-4">
        <div className="grid gap-3 sm:grid-cols-4">
          <Input label="Full name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          <Input label="Email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <Input label="Mobile (optional)" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          <Select label="Role" value={f.staff_role} onChange={(e) => setF({ ...f, staff_role: e.target.value })}
            options={[{ value: "attendant", label: "Attendant" }, ...(isOwner ? [{ value: "manager", label: "Manager" }] : [])]} />
        </div>
        <Button className="mt-3" busy={busy} disabled={!f.full_name || !f.email} onClick={add}>Add</Button>
      </Card>
      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : (
        <Card>
          <ul className="divide-y divide-slate-100">
            {data!.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div>
                  <p className="font-medium">{m.full_name} <Badge color="blue">{m.staff_role}</Badge> {!m.is_active && <Badge>inactive</Badge>}</p>
                  <p className="text-xs text-slate-500">{m.email} · {m.must_change_password ? "hasn't logged in yet" : m.last_login_at ? `last login ${when(m.last_login_at)}` : ""}</p>
                </div>
                {m.staff_role !== "owner" && (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => void run(async () => { await api(`/api/business/staff/${m.id}`, { method: "PATCH", json: { is_active: !m.is_active } }); await reload(); })}>
                      {m.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                    <Button variant="ghost" onClick={() => void run(async () => {
                      const out = await api<{ temporary_password: string }>(`/api/business/staff/${m.id}/reset-password`, { method: "POST" });
                      setSecret(`${m.full_name}'s new temporary password: ${out.temporary_password}`);
                    })}>Reset password</Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

// ---------- Business profile ----------

interface Profile { business_name: string; description: string | null; contact_phone: string | null; contact_email: string | null;
  address_line: string | null; suburb: string | null; city: string | null; latitude: number | null; longitude: number | null;
  verification_status: string; rejection_reason: string | null; registration_number: string | null }

export function BusinessProfile() {
  const { data, error, loading, setData } = useAsync(() => api<Profile>("/api/business/profile"));
  const { busy, error: saveError, run } = useAction();
  const [saved, setSaved] = useState(false);
  if (loading) return <Spinner />;
  if (error || !data) return <Alert>{error}</Alert>;
  const set = (k: keyof Profile) => (e: { target: { value: string } }) => { setSaved(false); setData({ ...data, [k]: e.target.value }); };
  const place: AddressValue = {
    address_line: data.address_line ?? "", suburb: data.suburb ?? "", city: data.city ?? "",
    latitude: data.latitude, longitude: data.longitude,
  };
  const setPlace = (p: AddressValue) => {
    setSaved(false);
    setData({ ...data, address_line: p.address_line, suburb: p.suburb, city: p.city, latitude: p.latitude, longitude: p.longitude });
  };
  const save = () => void run(async () => {
    setData(await api<Profile>("/api/business/profile", { method: "PATCH", json: {
      business_name: data.business_name, description: data.description || null, contact_phone: data.contact_phone || null,
      contact_email: data.contact_email || null, address_line: data.address_line, suburb: data.suburb, city: data.city,
      latitude: data.latitude, longitude: data.longitude,
    } }));
    setSaved(true);
  });
  return (
    <div className="max-w-2xl">
      <PageTitle sub={<>Verification: <StatusBadge status={data.verification_status} /> {data.registration_number && `· CIPC ${data.registration_number}`}</>}>Business profile</PageTitle>
      <Card>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Business name" value={data.business_name} onChange={set("business_name")} />
          <Input label="Contact phone" value={data.contact_phone ?? ""} onChange={set("contact_phone")} />
          <div className="sm:col-span-2"><TextArea label="Description" value={data.description ?? ""} onChange={set("description")} /></div>
          <Input label="Contact email" value={data.contact_email ?? ""} onChange={set("contact_email")} />
          <div className="sm:col-span-2">
            <AddressPicker label="Business address" value={place} onChange={setPlace} required />
            <p className="mt-1 text-xs text-slate-500">Customers find you, and drivers navigate to you, by where the pin is.</p>
          </div>
        </div>
        <div className="mt-3 space-y-2">
          <Alert>{saveError}</Alert>
          {saved && <Alert kind="success">Saved.</Alert>}
          <Button busy={busy} onClick={save}>Save changes</Button>
        </div>
      </Card>
      <p className="mt-2 text-xs text-slate-500">Prices shown to customers, e.g. {rands(2500)} per kg, are managed under Services.</p>
    </div>
  );
}
