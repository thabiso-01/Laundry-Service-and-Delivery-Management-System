import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { LaundrySearchItem, Page } from "../../api/types";
import { Alert, Button, Card, Empty, Input, PageTitle, Select, Spinner, Stars } from "../../components/ui";
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
    try {
      const pos = await currentPosition();
      update({ lat: pos.latitude.toFixed(5), lng: pos.longitude.toFixed(5) });
    } catch (e) {
      setLocError((e as Error).message + ". Showing laundries near Johannesburg CBD.");
    }
  };

  const usingDefault = !params.get("lat");

  return (
    <div>
      <PageTitle sub={usingDefault ? "Showing results near Johannesburg CBD." : `Near ${lat.toFixed(4)}, ${lng.toFixed(4)}`}>
        Find a laundry near you
      </PageTitle>
      <Card className="mb-4">
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
          <div className="lg:col-span-2">
            <Input label="Search" placeholder="Name, suburb or city" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
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
          <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
            <Button type="submit">Search</Button>
            <Button type="button" variant="secondary" onClick={locate}>📍 Use my location</Button>
          </div>
        </form>
        {locError && <div className="mt-3"><Alert kind="warning">{locError}</Alert></div>}
      </Card>

      {loading ? <Spinner /> : error ? <Alert>{error}</Alert> : !data?.items.length ? (
        <Empty>No laundries found. Try a wider distance or another service.</Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.items.map((l) => (
            <Link key={l.id} to={`/laundries/${l.id}?lat=${lat}&lng=${lng}`}
              className="block rounded-2xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-300 hover:shadow">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-slate-900">{l.business_name}</h3>
                  <p className="text-sm text-slate-500">{[l.suburb, l.city].filter(Boolean).join(", ")}</p>
                </div>
                <span className="whitespace-nowrap text-sm font-medium text-slate-700">{l.distance_km.toFixed(1)} km</span>
              </div>
              <div className="mt-2"><Stars value={l.rating_avg} count={l.rating_count} /></div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
                <span>{l.from_price_display}</span>
                <span>Ready in {l.fastest_turnaround_hours} h</span>
                <span>{l.service_count} service{l.service_count === 1 ? "" : "s"}</span>
              </div>
              {l.matching_services && (
                <ul className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-sm">
                  {l.matching_services.map((s) => (
                    <li key={s.id} className="flex justify-between"><span>{s.name}</span><span className="text-slate-600">{s.price_display}</span></li>
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
