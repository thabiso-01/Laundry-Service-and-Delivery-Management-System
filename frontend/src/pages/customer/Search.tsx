import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundrySearchItem, Page } from "../../api/types";
import { Icon } from "../../components/icons";
import { Alert, Button, Card, Empty, PageTitle, Select, Spinner, Stars } from "../../components/ui";
import { CATEGORIES, DEFAULT_LOCATION, currentPosition, label } from "../../lib/format";
import { useAsync } from "../../lib/useAsync";

// UR-005 / UR-006: find nearby laundries and compare them
export function Search() {
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

  return (
    <div>
      <PageTitle sub="Compare prices, ratings and turnaround times, then book a collection.">Find a laundry</PageTitle>

      <Card className="mb-6">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input aria-label="Search" placeholder="Search by name, suburb or city" value={q} onChange={(e) => setQ(e.target.value)}
                className="block h-11 w-full rounded-lg border-0 bg-white pl-9 pr-3 text-sm shadow-sm ring-1 ring-inset ring-slate-300 outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600" />
            </div>
            <div className="flex gap-2">
              <Button type="submit" className="h-11 flex-1 sm:flex-none">Search</Button>
              <Button type="button" variant="secondary" icon="navigation" className="h-11 flex-1 sm:flex-none" busy={locating} onClick={locate}>Use my location</Button>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Select label="Service" value={category} onChange={(e) => update({ category: e.target.value })}
              options={[{ value: "", label: "Any service" }, ...CATEGORIES.map((c) => ({ value: c, label: label(c) }))]} />
            <Select label="Distance" value={radius} onChange={(e) => update({ radius: e.target.value })}
              options={["5", "10", "15", "25", "50"].map((r) => ({ value: r, label: `Within ${r} km` }))} />
            <Select label="Sort by" value={sort} onChange={(e) => update({ sort: e.target.value })}
              options={[
                { value: "distance", label: "Closest" },
                { value: "rating", label: "Best rated" },
                { value: "turnaround", label: "Fastest" },
                ...(category ? [{ value: "price", label: "Cheapest" }] : []),
              ]} />
          </div>
        </form>
        {locError && <div className="mt-4"><Alert kind="warning">{locError}</Alert></div>}
      </Card>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <Icon name="pin" className="h-4 w-4" />
          {usingDefault ? "Near Johannesburg CBD" : "Near your location"}
        </span>
        {data && <span>{data.items.length} {data.items.length === 1 ? "laundry" : "laundries"}</span>}
      </div>

      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
        <Card><Empty icon="search" title="No laundries found">Try a wider distance or another service.</Empty></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.items.map((l) => (
            <Link key={l.id} to={`/laundries/${l.id}?lat=${lat}&lng=${lng}`}
              className="group flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-card transition hover:border-brand-300 hover:shadow-raised">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700"><Icon name="washer" /></span>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-slate-900 group-hover:text-brand-700">{l.business_name}</h3>
                  <p className="truncate text-sm text-slate-500">{[l.suburb, l.city].filter(Boolean).join(", ")}</p>
                  <div className="mt-1"><Stars value={l.rating_avg} count={l.rating_count} /></div>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-slate-600">{l.distance_km.toFixed(1)} km</span>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-slate-100 pt-4 text-sm">
                <div><p className="text-xs text-slate-500">Price</p><p className="font-medium text-slate-900">{l.from_price_display}</p></div>
                <div><p className="text-xs text-slate-500">Ready in</p><p className="font-medium text-slate-900">{l.fastest_turnaround_hours} h</p></div>
                <div><p className="text-xs text-slate-500">Services</p><p className="font-medium text-slate-900">{l.service_count}</p></div>
              </div>
              {l.matching_services && (
                <ul className="mt-4 space-y-1.5 rounded-lg bg-slate-50 p-3 text-sm">
                  {l.matching_services.map((s) => (
                    <li key={s.id} className="flex justify-between gap-2"><span className="text-slate-700">{s.name}</span><span className="font-medium text-slate-900">{s.price_display}</span></li>
                  ))}
                </ul>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
