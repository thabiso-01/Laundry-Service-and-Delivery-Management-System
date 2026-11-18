import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Me, TokenOut } from "../api/types";
import { homeFor, useAuth } from "../auth/AuthContext";
import { AddressPicker, EMPTY_ADDRESS, type AddressValue } from "../components/AddressPicker";
import { Icon, type IconName } from "../components/icons";
import { Alert, Button, ButtonLink, Checkbox, Input, Select, Spinner } from "../components/ui";
import { useAction } from "../lib/useAsync";

// ---------- Welcome page ----------

const HOW: [IconName, string, string][] = [
  ["search", "Choose a laundry", "Compare nearby laundries by price, rating and turnaround time."],
  ["clock", "Book a collection", "Pick a two-hour window. Pay securely online."],
  ["truck", "We collect & deliver", "A verified driver seals your bag and brings it back clean."],
  ["checkCircle", "Track every step", "See where your laundry is, from your door and back again."],
];

const TRUST: [IconName, string, string][] = [
  ["key", "One-time codes", "Your bag is only handed over when you give the driver your code at the door."],
  ["scan", "QR-labelled bags", "Each bag gets a signed label. Fake or swapped labels are rejected."],
  ["seal", "Tamper-evident seals", "Seal numbers are recorded and checked at every handover."],
  ["shield", "Verified partners", "Every laundry and driver is checked by our team before they can work."],
];

export function Landing() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (me) return <Navigate to={homeFor(me)} replace />;
  const deleted = new URLSearchParams(window.location.search).get("deleted") === "1";
  return (
    <div>
      {deleted && (
        <div className="mx-auto max-w-6xl px-4 pt-6 sm:px-6">
          <Alert kind="success">Your account has been deleted. Thank you for using LaundryConnect.</Alert>
        </div>
      )}

      {/* Hero */}
      <section className="relative overflow-hidden bg-gradient-to-b from-brand-50 to-slate-50">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-2 lg:py-10">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full bg-surface px-3 py-1 text-xs font-medium text-brand-800 shadow-sm ring-1 ring-brand-100">
              <Icon name="pin" className="h-3.5 w-3.5" /> Now serving Johannesburg
            </span>
            <h1 className="mt-5 text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
              Clean laundry,<br />collected and delivered.
            </h1>
            <p className="mt-5 max-w-lg text-lg text-slate-600">
              Book a trusted local laundry in a minute. We collect from your door and bring it back clean, with every
              handover verified.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink to="/search" size="lg" icon="search">Find a laundry</ButtonLink>
              <ButtonLink to="/register" size="lg" variant="secondary">Create an account</ButtonLink>
            </div>
          </div>

          {/* Preview of an order */}
          <div className="relative mx-auto w-full max-w-md lg:ml-auto">
            <img src="/images/hero-linen.jpg" alt="Freshly washed linen, neatly folded" width={800} height={1422}
              className="aspect-[4/5] w-full rounded-3xl object-cover object-bottom shadow-raised sm:aspect-square" fetchPriority="high" />
            <div className="absolute inset-x-4 bottom-4 rounded-2xl border border-white/60 bg-surface/95 p-4 shadow-raised backdrop-blur sm:inset-x-5 sm:bottom-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-slate-500">Order LC-7K2M9QX4</p>
                  <p className="truncate font-semibold text-slate-900">Braam Fresh Laundry</p>
                </div>
                <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700 ring-1 ring-violet-600/20 ring-inset">
                  <span className="h-1.5 w-1.5 rounded-full bg-violet-500" /> On the way
                </span>
              </div>
              <div className="mt-3 flex items-center gap-3">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100"><div className="h-full w-[85%] rounded-full bg-brand-600" /></div>
                <span className="text-xs font-medium text-slate-500">Step 7 of 8</span>
              </div>
              <ul className="mt-3 space-y-2 text-sm">
                {[["Collected · code confirmed", "09:12"], ["Checked in · seal intact", "10:05"], ["Washed, dried and folded", "15:40"]].map(([t, time]) => (
                  <li key={t} className="flex items-center gap-2.5">
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-emerald-50 text-emerald-600">
                      <Icon name="check" className="h-3 w-3" />
                    </span>
                    <span className="flex-1 truncate text-slate-600">{t}</span>
                    <span className="font-mono text-xs text-slate-400">{time}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex items-center gap-3 rounded-xl bg-brand-50 px-3 py-2.5">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-600 text-white">
                  <Icon name="truck" className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-900">Sipho is on the way</p>
                  <p className="text-xs text-slate-600">Arriving around 17:30</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="text-2xl font-semibold tracking-tight text-slate-900">How it works</h2>
        <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {HOW.map(([icon, title, text], i) => (
            <div key={title}>
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 place-items-center rounded-lg bg-deep text-white"><Icon name={icon} /></span>
                <span className="text-sm font-medium text-slate-400">Step {i + 1}</span>
              </div>
              <h3 className="mt-4 font-semibold text-slate-900">{title}</h3>
              <p className="mt-1 text-sm text-slate-600">{text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Trust */}
      <section className="border-y border-slate-200 bg-surface">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900">Your clothes never go missing</h2>
            <p className="mt-2 text-slate-600">Every time your bag changes hands, it's checked and recorded, so you always know who has it.</p>
          </div>
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {TRUST.map(([icon, title, text]) => (
              <div key={title} className="rounded-xl border border-slate-200 p-5">
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-emerald-50 text-emerald-700"><Icon name={icon} className="h-[18px] w-[18px]" /></span>
                <h3 className="mt-4 font-semibold text-slate-900">{title}</h3>
                <p className="mt-1 text-sm text-slate-600">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Partners */}
      <section className="mx-auto grid max-w-6xl gap-5 px-4 py-16 sm:px-6 md:grid-cols-2">
        {([
          ["store", "Run a laundry?", "Get paid orders from customers nearby. Manage services, prices and staff in one place.", "List your laundry", "/images/laundry-shop.jpg"],
          ["truck", "Have a vehicle?", "Pick up collection and delivery jobs near you and get paid for every trip.", "Drive with us", null],
        ] as [IconName, string, string, string, string | null][]).map(([icon, title, text, cta, photo]) => (
          <div key={title} className="relative isolate flex min-h-72 flex-col overflow-hidden rounded-2xl bg-ink-900 p-7 text-white">
            {photo ? (
              <>
                <img src={photo} alt="" loading="lazy" className="absolute inset-0 -z-10 h-full w-full object-cover" />
                <div className="absolute inset-0 -z-10 bg-gradient-to-t from-ink-950/95 via-ink-900/75 to-ink-900/30" />
              </>
            ) : (
              <div className="absolute inset-0 -z-10 bg-gradient-to-br from-deep-900 via-ink-900 to-ink-950" />
            )}
            <Icon name={icon} className="h-7 w-7 text-brand-300" />
            <h3 className="mt-4 text-xl font-semibold">{title}</h3>
            <p className="mt-2 flex-1 text-white/75">{text}</p>
            <Link to="/register" className="mt-6 inline-flex items-center gap-1.5 self-start font-medium text-brand-300 hover:text-white">
              {cta} <Icon name="arrowRight" className="h-4 w-4" />
            </Link>
          </div>
        ))}
      </section>
    </div>
  );
}

// ---------- Shared frame for the account forms ----------

function AuthFrame({ title, sub, children, footer, wide, photo = true }: { title: string; sub?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean; photo?: boolean }) {
  const { me } = useAuth();
  const form = <FormColumn title={title} sub={sub} footer={footer} wide={wide}>{children}</FormColumn>;
  if (!photo || me) return form;
  return (
    <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,1fr)_420px]">
      {form}
      <aside className="relative hidden overflow-hidden rounded-3xl lg:sticky lg:top-24 lg:block">
        <img src="/images/laundry-basket.jpg" alt="A basket of laundry ready to be collected" className="aspect-[4/5] w-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950/85 via-ink-900/20 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 p-7 text-white">
          <p className="text-xl font-semibold">Leave the laundry to us.</p>
          <ul className="mt-4 space-y-2 text-sm text-white/80">
            {["Collected from your door", "Cleaned by verified local laundries", "Sealed and tracked at every step"].map((t) => (
              <li key={t} className="flex items-center gap-2"><Icon name="checkCircle" className="h-4 w-4 text-emerald-400" />{t}</li>
            ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}

function FormColumn({ title, sub, children, footer, wide }: { title: string; sub?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto w-full ${wide ? "max-w-xl" : "max-w-md"} py-4 sm:py-8`}>
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {sub && <p className="mt-1.5 text-sm text-slate-500">{sub}</p>}
      </div>
      <div className="rounded-2xl border border-slate-200 bg-surface p-6 shadow-card sm:p-8">{children}</div>
      {footer && <p className="mt-6 text-center text-sm text-slate-600">{footer}</p>}
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
    <AuthFrame
      title={mfaToken ? "Two-step sign-in" : "Welcome back"}
      sub={mfaToken ? "Enter the code from your authenticator app." : "Log in to your LaundryConnect account."}
      footer={!mfaToken && <>New here? <Link to="/register" className="font-medium text-brand-700 hover:underline">Create an account</Link></>}
    >
      <form onSubmit={submit} className="space-y-5">
        {mfaToken ? (
          <Input label="Authentication code" inputMode="numeric" autoFocus value={code} className="text-center font-mono text-lg tracking-[0.3em]"
            onChange={(e) => setCode(e.target.value)} hint="Lost your phone? Enter one of your recovery codes instead." required />
        ) : (
          <>
            <Input label="Email" type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} required />
            <Input label="Password" type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </>
        )}
        <Alert>{error}</Alert>
        <Button type="submit" size="lg" busy={busy} className="w-full">{mfaToken ? "Verify" : "Log in"}</Button>
      </form>
    </AuthFrame>
  );
}

type Kind = "customer" | "driver" | "business";

const KINDS: { kind: Kind; icon: IconName; title: string; text: string }[] = [
  { kind: "customer", icon: "user", title: "Customer", text: "I need laundry done" },
  { kind: "driver", icon: "truck", title: "Driver", text: "I want delivery work" },
  { kind: "business", icon: "store", title: "Laundry", text: "I run a laundry" },
];

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
    <AuthFrame wide title="Create your account"
      sub={kind === "customer" ? "It takes less than a minute." : "We check every driver and laundry before they can take work."}
      footer={<>Already have an account? <Link to="/login" className="font-medium text-brand-700 hover:underline">Log in</Link></>}>
      <fieldset className="mb-6">
        <legend className="mb-2 text-sm font-medium text-slate-700">I'm signing up as a…</legend>
        <div className="grid grid-cols-3 gap-2">
          {KINDS.map((k) => (
            <button key={k.kind} type="button" onClick={() => setKind(k.kind)} aria-pressed={kind === k.kind}
              className={`flex flex-col items-center gap-1 rounded-xl border px-2 py-3 text-center transition ${
                kind === k.kind ? "border-brand-600 bg-brand-50 ring-1 ring-brand-600" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"}`}>
              <Icon name={k.icon} className={kind === k.kind ? "h-5 w-5 text-brand-700" : "h-5 w-5 text-slate-400"} />
              <span className="text-sm font-semibold text-slate-900">{k.title}</span>
              <span className="hidden text-xs text-slate-500 sm:block">{k.text}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <form onSubmit={submit} className="space-y-4">
        {kind === "business" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Business name" value={f.business_name ?? ""} onChange={set("business_name")} required />
            <Input label="CIPC registration number" value={f.registration_number ?? ""} onChange={set("registration_number")} placeholder="2020/123456/07" />
          </div>
        )}
        <Input label={kind === "business" ? "Owner's full name" : "Full name"} value={f.full_name ?? ""} onChange={set("full_name")} autoComplete="name" required />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Email" type="email" value={f.email ?? ""} onChange={set("email")} autoComplete="email" required />
          <Input label="Mobile number" type="tel" value={f.phone ?? ""} onChange={set("phone")} placeholder="082 123 4567" autoComplete="tel" />
        </div>
        <Input label="Password" type="password" value={f.password ?? ""} onChange={set("password")} minLength={10} autoComplete="new-password"
          hint="At least 10 characters" required />
        {kind === "driver" && (
          <>
            <Input label="SA ID or passport number" value={f.id_number ?? ""} onChange={set("id_number")} required />
            <div className="grid grid-cols-2 gap-4">
              <Select label="Vehicle" value={f.vehicle_type} onChange={set("vehicle_type")}
                options={["car", "bakkie", "van", "motorcycle", "bicycle"].map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }))} />
              <Input label="Registration" value={f.vehicle_registration ?? ""} onChange={set("vehicle_registration")} placeholder="GP 123-456" />
            </div>
          </>
        )}
        {kind !== "driver" && (
          <fieldset className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
            <legend className="px-1 text-sm font-medium text-slate-700">{kind === "business" ? "Business address" : "Home address (optional)"}</legend>
            <AddressPicker label={kind === "business" ? "Business address" : "Home address"} value={place} onChange={setPlace}
              required={kind === "business"} />
            {kind === "business" && <p className="text-xs text-slate-500">Customers find you by where the pin is.</p>}
          </fieldset>
        )}
        <div className="border-t border-slate-100 pt-4">
          <Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)}
            label="I agree to the privacy policy and allow LaundryConnect to process my personal information (POPIA)." />
        </div>
        <Alert>{error}</Alert>
        <Button type="submit" size="lg" busy={busy} disabled={!consent} className="w-full">Create account</Button>
      </form>
    </AuthFrame>
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
    <AuthFrame title="Change password" sub={forced ? "Choose your own password before you start." : "Use at least 10 characters."}>
      <form onSubmit={submit} className="space-y-5">
        <Input label={forced ? "Temporary password" : "Current password"} type="password" value={current}
          onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
        <Input label="New password" type="password" value={next} onChange={(e) => setNext(e.target.value)} minLength={10}
          autoComplete="new-password" hint="At least 10 characters" required />
        {forced && (
          <Checkbox checked={consent} onChange={(e) => setConsent(e.target.checked)}
            label="I agree to the privacy policy (POPIA)." />
        )}
        <Alert>{error}</Alert>
        <Button type="submit" size="lg" busy={busy} className="w-full">Save password</Button>
      </form>
    </AuthFrame>
  );
}
