// Formatting helpers. South Africa is UTC+2 all year (no daylight saving).

// Same style as the backend's price_display: R1 250.50 (space for thousands,
// point for cents) so amounts look identical everywhere in the app
export function rands(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const [whole, fraction] = (Math.abs(cents) / 100).toFixed(2).split(".");
  return `${sign}R${whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ")}.${fraction}`;
}

const dateTime = new Intl.DateTimeFormat("en-ZA", {
  timeZone: "Africa/Johannesburg",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const timeOnly = new Intl.DateTimeFormat("en-ZA", {
  timeZone: "Africa/Johannesburg",
  hour: "2-digit",
  minute: "2-digit",
});

export function when(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function windowText(start: string, end: string): string {
  return `${dateTime.format(new Date(start))} – ${timeOnly.format(new Date(end))}`;
}

export function label(value: string): string {
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const CATEGORIES = [
  "wash_and_fold", "wash_and_iron", "ironing", "dry_cleaning",
  "bedding", "shoes", "speciality", "other",
];

export const UNIT_LABEL: Record<string, string> = {
  per_kg: "kg",
  per_item: "items",
  per_load: "loads",
};

// ---------- Time slots (UR-008) ----------
// Slots are 2-hour windows between 07:00 and 19:00 SAST, matching the backend rules.

export interface Slot {
  start: string;
  end: string;
  label: string;
}

function sastIso(year: number, month: number, day: number, hour: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month)}-${pad(day)}T${pad(hour)}:00:00+02:00`;
}

export function slots(daysAhead = 14, from = new Date()): Slot[] {
  const out: Slot[] = [];
  const earliest = from.getTime() + 60 * 60 * 1000; // 1 hour lead time
  // Today's date in South Africa
  const sa = new Date(from.getTime() + 2 * 3600 * 1000);
  for (let d = 0; d <= daysAhead; d++) {
    const day = new Date(Date.UTC(sa.getUTCFullYear(), sa.getUTCMonth(), sa.getUTCDate() + d));
    for (let h = 7; h <= 17; h += 2) {
      const start = sastIso(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h);
      if (new Date(start).getTime() < earliest) continue;
      const end = sastIso(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h + 2);
      out.push({ start, end, label: windowText(start, end) });
    }
  }
  return out;
}

export function osmLink(lat: number, lng: number): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`;
}

// Johannesburg CBD, used when the browser won't share a location
export const DEFAULT_LOCATION = { latitude: -26.2041, longitude: 28.0473 };

export function currentPosition(): Promise<{ latitude: number; longitude: number }> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("Location isn't available"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
      () => reject(new Error("Location permission was refused")),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  });
}
