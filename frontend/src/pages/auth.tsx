import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Me, TokenOut } from "../api/types";
import { homeFor, useAuth } from "../auth/AuthContext";
import { AddressPicker, EMPTY_ADDRESS, type AddressValue } from "../components/AddressPicker";
import { Alert, Button, Card, Checkbox, Input, PageTitle, Select, Spinner } from "../components/ui";
import { useAction } from "../lib/useAsync";

export function Landing() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (me) return <Navigate to={homeFor(me)} replace />;
  return (
    <div className="mx-auto max-w-3xl py-10 text-center">
      <h1 className="text-3xl font-bold text-slate-900 sm:text-4xl">Clean laundry, collected and delivered</h1>
      <p className="mt-3 text-slate-600">
        Find a trusted laundry near you, book a collection, and track your laundry until it's back at your door.
        Every handover is verified with one-time codes, QR-coded bags and tamper-evident seals.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <Link to="/search" className="rounded-lg bg-sky-700 px-5 py-2.5 font-medium text-white">Find a laundry</Link>
        <Link to="/register" className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 font-medium text-slate-800">Create an account</Link>
      </div>
      <div className="mt-10 grid gap-4 text-left sm:grid-cols-3">
        {[
          ["For customers", "Compare prices and turnaround times, pay securely, and watch your driver on the way."],
          ["For laundries", "Receive paid orders, manage your services and staff, and reach new customers."],
          ["For drivers", "Pick up nearby collection and delivery jobs and get paid per trip."],
        ].map(([t, d]) => (
          <Card key={t} title={t}><p className="text-sm text-slate-600">{d}</p></Card>
        ))}
      </div>
    </div>
  );
}

export function Login() {
  const { login, loginMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const { busy, error, run } = useAction();

  const finish = (me: Me) => {
    const from = location.state?.from;
    navigate(me.must_change_password ? "/change-password" : from || homeFor(me), { replace: true });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (mfaToken) return finish(await loginMfa(mfaToken, code));
      const result = await login(email, password);
      if ("mfaToken" in result) setMfaToken(result.mfaToken);
      else finish(result.me);
    });
  };

  return (
    <div className="mx-auto max-w-sm">
      <PageTitle>{mfaToken ? "Two-step sign-in" : "Log in"}</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          {mfaToken ? (
            <Input label="Code from your authenticator app" inputMode="numeric" autoFocus value={code}
              onChange={(e) => setCode(e.target.value)} hint="Or enter one of your recovery codes" required />
          ) : (
            <>
              <Input label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <Input label="Password" type="password" autoComplete="current-password" value={password}
                onChange={(e) => setPassword(e.target.value)} required />
            </>
          )}
          <Alert>{error}</Alert>
          <Button type="submit" busy={busy} className="w-full">{mfaToken ? "Verify" : "Log in"}</Button>
        </form>
        {!mfaToken && (
          <p className="mt-4 text-center text-sm text-slate-600">
            New here? <Link to="/register" className="text-sky-700 underline">Create an account</Link>
          </p>
        )}
      </Card>
    </div>
  );
}

type Kind = "customer" | "driver" | "business";

export function Register() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [kind, setKind] = useState<Kind>("customer");
  const [f, setF] = useState<Record<string, string>>({ vehicle_type: "car" });
  const [consent, setConsent] = useState(false);
  const [place, setPlace] = useState<AddressValue>(EMPTY_ADDRESS);
  const { busy, error, run } = useAction();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const base = {
        email: f.email, password: f.password, full_name: f.full_name,
        phone: f.phone || null, accept_privacy_policy: consent,
      };
      if (kind === "business" && place.latitude == null) {
        throw new Error("Place your business on the map so customers can find you");
      }
      const address = {
        address_line: place.address_line || null, suburb: place.suburb || null, city: place.city || null,
        province: place.province || null, postal_code: place.postal_code || null,
        latitude: place.latitude, longitude: place.longitude,
      };
      const body =
        kind === "customer" ? { ...base, address }
        : kind === "driver" ? { ...base, id_number: f.id_number, vehicle_type: f.vehicle_type, vehicle_registration: f.vehicle_registration || null }
        : { ...base, business_name: f.business_name, registration_number: f.registration_number || null,
            contact_phone: f.contact_phone || null, description: f.description || null, address };
      await api(`/api/auth/register/${kind}`, { json: body });
      const result = await login(f.email, f.password);
      if ("me" in result) navigate(kind === "customer" ? "/search" : "/documents", { replace: true });
    });
  };

  return (
    <div className="mx-auto max-w-lg">
      <PageTitle sub="Drivers and laundries are checked by our team before they can take work.">Create an account</PageTitle>
      <div className="mb-4 grid grid-cols-3 gap-1 rounded-xl bg-slate-200 p-1 text-sm">
        {(["customer", "driver", "business"] as Kind[]).map((k) => (
          <button key={k} onClick={() => setKind(k)}
            className={`rounded-lg py-2 ${kind === k ? "bg-white font-medium shadow" : "text-slate-600"}`}>
            {k === "customer" ? "I need laundry done" : k === "driver" ? "I'm a driver" : "I run a laundry"}
          </button>
        ))}
      </div>
      <Card>
        <form onSubmit={submit} className="space-y-3">
          {kind === "business" && (
            <>
              <Input label="Business name" value={f.business_name ?? ""} onChange={set("business_name")} required />
              <Input label="CIPC registration number" value={f.registration_number ?? ""} onChange={set("registration_number")} placeholder="2020/123456/07" />
            </>
          )}
          <Input label={kind === "business" ? "Owner's full name" : "Full name"} value={f.full_name ?? ""} onChange={set("full_name")} required />
          <Input label="Email" type="email" value={f.email ?? ""} onChange={set("email")} required />
          <Input label="Mobile number" value={f.phone ?? ""} onChange={set("phone")} placeholder="082 123 4567" />
          <Input label="Password" type="password" value={f.password ?? ""} onChange={set("password")} minLength={10}
            hint="At least 10 characters" required />
          {kind === "driver" && (
            <>
              <Input label="SA ID or passport number" value={f.id_number ?? ""} onChange={set("id_number")} required />
              <div className="grid grid-cols-2 gap-3">
                <Select label="Vehicle" value={f.vehicle_type} onChange={set("vehicle_type")}
                  options={["car", "bakkie", "van", "motorcycle", "bicycle"].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))} />
                <Input label="Registration" value={f.vehicle_registration ?? ""} onChange={set("vehicle_registration")} placeholder="GP 123-456" />
              </div>
            </>
          )}
          {kind !== "driver" && (
            <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
              <legend className="px-1 text-sm font-medium text-slate-700">{kind === "business" ? "Business address" : "Home address (optional)"}</legend>
              <AddressPicker label={kind === "business" ? "Business address" : "Home address"} value={place} onChange={setPlace}
                required={kind === "business"} />
              {kind === "business" && <p className="text-xs text-slate-500">Customers find you by where the pin is.</p>}
            </fieldset>
          )}
          <Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)}
            label="I agree to the privacy policy and allow LaundryConnect to process my personal information (POPIA)." />
          <Alert>{error}</Alert>
          <Button type="submit" busy={busy} disabled={!consent} className="w-full">Create account</Button>
        </form>
      </Card>
    </div>
  );
}

export function ChangePassword() {
  const { me, adoptToken } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [consent, setConsent] = useState(false);
  const { busy, error, run } = useAction();
  const forced = me?.must_change_password;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const out = await api<TokenOut>("/api/auth/change-password", {
        json: { current_password: current, new_password: next, accept_privacy_policy: consent || null },
      });
      navigate(homeFor(await adoptToken(out.access_token!)), { replace: true });
    });
  };

  return (
    <div className="mx-auto max-w-sm">
      <PageTitle sub={forced ? "Choose your own password before you start." : undefined}>Change password</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Input label={forced ? "Temporary password" : "Current password"} type="password" value={current}
            onChange={(e) => setCurrent(e.target.value)} required />
          <Input label="New password" type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength={10}
            hint="At least 10 characters" required />
          {forced && (
            <Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)}
              label="I agree to the privacy policy (POPIA)." />
          )}
          <Alert>{error}</Alert>
          <Button type="submit" busy={busy} className="w-full">Save password</Button>
        </form>
      </Card>
    </div>
  );
}
