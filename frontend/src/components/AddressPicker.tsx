// Type an address → choose a suggestion → the pin shows on the map. Drag the
// pin or tap the map to correct it; the address fields fill in and stay editable.
// Searches go through our backend (/api/geocode), which forwards them to
// OpenStreetMap's Nominatim – customers' IP addresses are not shared.

import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { currentPosition } from "../lib/format";
import { MapView } from "./MapView";
import { Button, Input } from "./ui";

export interface AddressValue {
  address_line: string;
  suburb: string;
  city: string;
  province?: string;
  postal_code?: string;
  latitude: number | null;
  longitude: number | null;
}

interface Suggestion {
  label: string;
  address_line: string;
  suburb: string | null;
  city: string | null;
  province: string | null;
  postal_code: string | null;
  latitude: number;
  longitude: number;
}

export const EMPTY_ADDRESS: AddressValue = { address_line: "", suburb: "", city: "", latitude: null, longitude: null };

function merge(current: AddressValue, found: Suggestion, keepStreet: boolean): AddressValue {
  return {
    address_line: keepStreet && current.address_line ? current.address_line : found.address_line || current.address_line,
    suburb: found.suburb ?? current.suburb,
    city: found.city ?? current.city,
    province: found.province ?? current.province,
    postal_code: found.postal_code ?? current.postal_code,
    latitude: found.latitude,
    longitude: found.longitude,
  };
}

export function AddressPicker({ value, onChange, label = "Address", required }: {
  value: AddressValue;
  onChange: (next: AddressValue) => void;
  label?: string;
  required?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const latest = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;

  // Debounced search: waits until the user pauses typing (keeps within the
  // geocoder's fair-use limits)
  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) { setResults([]); return; }
    const id = ++latest.current;
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const found = await api<Suggestion[]>(`/api/geocode?q=${encodeURIComponent(q)}`);
        if (id !== latest.current) return; // a newer search is on its way
        setResults(found);
        setOpen(true);
        setMessage(found.length ? null : "No matches. Try the street and suburb, e.g. \"45 Juta St Braamfontein\".");
      } catch (e) {
        if (id === latest.current) setMessage((e as Error).message);
      } finally {
        if (id === latest.current) setSearching(false);
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [query]);

  const lookUp = async (lat: number, lng: number) => {
    onChange({ ...valueRef.current, latitude: lat, longitude: lng }); // move the pin straight away
    try {
      const found = await api<Suggestion>(`/api/geocode/reverse?lat=${lat}&lng=${lng}`);
      onChange(merge({ ...valueRef.current, latitude: lat, longitude: lng }, { ...found, latitude: lat, longitude: lng }, false));
      setMessage(null);
    } catch {
      setMessage("Pin placed. Check the street address below.");
    }
  };

  const here = async () => {
    try {
      const p = await currentPosition();
      await lookUp(Number(p.latitude.toFixed(6)), Number(p.longitude.toFixed(6)));
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const pinned = value.latitude != null && value.longitude != null;

  return (
    <div className="space-y-3">
      <div className="relative">
        <Input label={`Search for ${label.toLowerCase()}`} value={query} placeholder="Start typing a street and suburb…"
          onChange={(e) => setQuery(e.target.value)} onFocus={() => results.length && setOpen(true)}
          hint={searching ? "Searching…" : undefined} autoComplete="off" />
        {open && results.length > 0 && (
          <ul className="absolute z-[1000] mt-1 max-h-64 w-full overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg">
            {results.map((r, i) => (
              <li key={i}>
                <button type="button" className="block w-full px-3 py-2 text-left text-sm hover:bg-brand-50"
                  onClick={() => { onChange(merge(value, r, false)); setOpen(false); setQuery(""); setMessage(null); }}>
                  {r.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <Button type="button" variant="ghost" size="sm" icon="navigation" className="-ml-3" onClick={() => void here()}>Use my current location</Button>
      {message && <p className="text-sm text-amber-700">{message}</p>}

      {pinned ? (
        <>
          <MapView height={220} points={[{ latitude: value.latitude!, longitude: value.longitude!, draggable: true, label: "Drag me to the exact spot" }]}
            onDragEnd={(_, lat, lng) => void lookUp(lat, lng)} onPick={(lat, lng) => void lookUp(lat, lng)} />
          <p className="text-xs text-slate-500">Drag the pin (or tap the map) to the exact gate or door.</p>
        </>
      ) : (
        <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">Search above or use your location to place the pin.</p>
      )}

      <Input label="Street address" value={value.address_line} required={required}
        onChange={(e) => onChange({ ...value, address_line: e.target.value })} placeholder="45 Juta St, unit 3" />
      <div className="grid grid-cols-2 gap-2">
        <Input label="Suburb" value={value.suburb} onChange={(e) => onChange({ ...value, suburb: e.target.value })} />
        <Input label="City" value={value.city} required={required} onChange={(e) => onChange({ ...value, city: e.target.value })} />
      </div>
    </div>
  );
}
