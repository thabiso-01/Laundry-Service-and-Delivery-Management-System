import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundrySearchItem, Page } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Icon } from "../../components/icons";
import { Alert, Card, CoverImage, Empty, Spinner } from "../../components/ui";
import { CATEGORY_INFO, FEATURED_CATEGORIES } from "../../lib/categories";
import { DEFAULT_LOCATION, currentPosition } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";

const SORTS = [
  { value: "distance", label: "Closest" },
  { value: "rating", label: "Best rated" },
  { value: "turnaround", label: "Fastest" },
  { value: "price", label: "Cheapest" },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-medium whitespace-nowrap transition ${
        active ? "bg-brand-600 text-white shadow-sm shadow-brand-600/25" : "bg-surface text-slate-600 ring-1 ring-slate-200 hover:text-slate-900"}`}>
      {children}
    </button>
  );
}

// UR-005 / UR-006: find nearby laundries and compare them
export function Search() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const lat = Number(params.get("lat") ?? DEFAULT_LOCATION.latitude);
  const lng = Number(params.get("lng") ?? DEFAULT_LOCATION.longitude);
  const radius = params.get("radius") ?? "10";
  const category = params.get("category") ?? "";
  const sort = params.get("sort") ?? "distance";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [locError, setLocError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (next.get("sort") === "price" && !next.get("category")) next.set("sort", "distance");
    setParams(next, { replace: true });
  };

  const { data, error, loading } = useAsync(() => {
    const query = new URLSearchParams({ lat: String(lat), lng: String(lng), radius_km: radius, sort });
    if (category) query.set("category", category);
    if (params.get("q")) query.set("q", params.get("q")!);
    return api<Page<LaundrySearchItem>>(`/api/laundries?${query}`);
  }, [lat, lng, radius, category, sort, params.get("q")]);

  const locate = async () => {
    setLocError(null);
    setLocating(true);
    try {
      const pos = await currentPosition();
      update({ lat: pos.latitude.toFixed(5), lng: pos.longitude.toFixed(5) });
    } catch (e) {
      setLocError((e as Error).message + ". Showing laundries near Johannesburg CBD.");
    } finally {
      setLocating(false);
    }
  };

  const usingDefault = !params.get("lat");
  const firstName = me?.full_name.split(" ")[0];

  return (
    <div className="space-y-7">
      {/* Blue header: greeting, location, search */}
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-500 via-brand-600 to-deep p-5 text-white shadow-raised sm:p-7">
        <div aria-hidden className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full bg-surface/10" />
        <div aria-hidden className="pointer-events-none absolute -bottom-24 right-24 h-48 w-48 rounded-full bg-surface/5" />
        <div className="relative flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{firstName ? `Hi, ${firstName}!` : "Find a laundry"}</h1>
            <p className="mt-1 flex items-center gap-1.5 text-sm text-white/85">
              <Icon name="pin" className="h-4 w-4" />
              {usingDefault ? "Near Johannesburg CBD" : "Near your location"}
            </p>
          </div>
          <button type="button" onClick={() => void locate()} disabled={locating}
            className="inline-flex items-center gap-2 rounded-full bg-surface/15 px-4 py-2 text-sm font-medium ring-1 ring-white/25 backdrop-blur transition hover:bg-surface/25 disabled:opacity-70">
            {locating ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <Icon name="navigation" className="h-4 w-4" />}
            Use my location
          </button>
        </div>
        <form className="relative mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
          <div className="relative flex-1">
            <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input aria-label="Search" placeholder="Search laundries, suburbs or cities" value={q} onChange={(e) => setQ(e.target.value)}
              className="block h-12 w-full rounded-2xl border-0 bg-surface pl-11 pr-4 text-sm text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:ring-4 focus:ring-white/40" />
          </div>
          <button type="submit" aria-label="Search now" className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-surface text-brand-600 shadow-sm transition hover:bg-brand-50">
            <Icon name="arrowRight" />
          </button>
        </form>
        {locError && <p className="relative mt-3 rounded-xl bg-surface/15 px-3 py-2 text-sm">{locError}</p>}
      </section>

      {/* Services */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">Services</h2>
          {category && <button className="text-sm font-medium text-brand-600 hover:underline" onClick={() => update({ category: "", sort: sort === "price" ? "distance" : sort })}>Show all</button>}
        </div>
        <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-6 sm:overflow-visible sm:px-0">
          {FEATURED_CATEGORIES.map((c) => {
            const info = CATEGORY_INFO[c];
            const active = category === c;
            return (
              <button key={c} type="button" aria-pressed={active} onClick={() => update({ category: active ? "" : c, sort: active && sort === "price" ? "distance" : sort })}
                className="group flex w-20 shrink-0 flex-col items-center gap-2 sm:w-auto">
                <span className={`grid h-16 w-16 place-items-center rounded-full transition ${
                  active ? "bg-brand-600 text-white shadow-md shadow-brand-600/30" : "bg-surface text-brand-600 shadow-card ring-1 ring-slate-100 group-hover:bg-brand-50"}`}>
                  <Icon name={info.icon} className="h-7 w-7" />
                </span>
                <span className={`text-xs font-medium ${active ? "text-brand-700" : "text-slate-600"}`}>{info.name}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* Results */}
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">
            {category ? `${CATEGORY_INFO[category]?.name ?? "Laundries"} near you` : "Laundries near you"}
            {data && <span className="ml-2 text-sm font-normal text-slate-400">{data.items.length}</span>}
          </h2>
          <label className="flex items-center gap-2 text-sm text-slate-500">
            <span className="sr-only sm:not-sr-only">Within</span>
            <select aria-label="Distance" value={radius} onChange={(e) => update({ radius: e.target.value })}
              className="rounded-full border-0 bg-surface py-1.5 pl-3 pr-8 text-sm font-medium text-slate-700 ring-1 ring-slate-200 outline-none focus:ring-2 focus:ring-brand-600">
              {["5", "10", "15", "25", "50"].map((r) => <option key={r} value={r}>{r} km</option>)}
            </select>
          </label>
        </div>
        <div className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
          {SORTS.filter((s) => s.value !== "price" || category).map((s) => (
            <Chip key={s.value} active={sort === s.value} onClick={() => update({ sort: s.value })}>{s.label}</Chip>
          ))}
        </div>

        {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
          <Card><Empty icon="search" title="No laundries found">Try a wider distance or another service.</Empty></Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((l) => (
              <Link key={l.id} to={`/laundries/${l.id}?lat=${lat}&lng=${lng}`}
                className="group flex flex-col overflow-hidden rounded-3xl bg-surface p-2 shadow-card ring-1 ring-slate-100 transition hover:-translate-y-0.5 hover:shadow-raised">
                <div className="relative h-40 overflow-hidden rounded-2xl">
                  <CoverImage src={l.photo_url} name={l.business_name} className="h-full w-full transition duration-500 group-hover:scale-105" />
                  {l.rating_avg != null && (
                    <span className="absolute left-2.5 top-2.5 inline-flex items-center gap-1 rounded-full bg-surface/95 px-2 py-0.5 text-xs font-semibold text-slate-800 shadow-sm">
                      <Icon name="star" className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />{l.rating_avg.toFixed(1)}
                      <span className="font-normal text-slate-500">({l.rating_count})</span>
                    </span>
                  )}
                  <span className="absolute right-2.5 top-2.5 rounded-full bg-ink-900/60 px-2 py-0.5 text-xs font-medium text-white backdrop-blur">{l.distance_km.toFixed(1)} km</span>
                </div>
                <div className="flex flex-1 flex-col px-3 pb-3 pt-3">
                  <h3 className="font-semibold text-slate-900 group-hover:text-brand-700">{l.business_name}</h3>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1"><Icon name="pin" className="h-3.5 w-3.5" />{[l.suburb, l.city].filter(Boolean).join(", ")}</span>
                    <span className="inline-flex items-center gap-1"><Icon name="clock" className="h-3.5 w-3.5" />Ready in {l.fastest_turnaround_hours} h</span>
                  </p>
                  {l.matching_services && (
                    <ul className="mt-3 space-y-1 text-sm">
                      {l.matching_services.map((s) => (
                        <li key={s.id} className="flex justify-between gap-2"><span className="text-slate-600">{s.name}</span><span className="font-medium text-slate-900">{s.price_display}</span></li>
                      ))}
                    </ul>
                  )}
                  <div className="mt-auto flex items-center justify-between pt-4">
                    <span className="text-sm"><span className="text-slate-500">{l.service_count} services · </span><span className="font-semibold text-brand-600">{l.from_price_display}</span></span>
                    <span className="rounded-full bg-brand-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm shadow-brand-600/25">Select</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
