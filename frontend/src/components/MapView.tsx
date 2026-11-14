// A small Leaflet map with OpenStreetMap tiles. Leaflet (~150 kB) is only
// downloaded on pages that actually show a map.
//
// OpenStreetMap's tile servers are fine for development and light use; for a
// busy production site switch TILE_URL to a tile provider (MapTiler, Stadia,
// Thunderforest…) per OSM's tile usage policy.

import { useEffect, useRef, useState } from "react";
import type * as Leaflet from "leaflet";

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export interface MapPoint {
  latitude: number;
  longitude: number;
  label?: string;
  color?: "blue" | "green" | "orange" | "red" | "grey";
  draggable?: boolean;
}

const COLORS = { blue: "#0369a1", green: "#047857", orange: "#c2410c", red: "#be123c", grey: "#475569" };

let leafletLoading: Promise<typeof Leaflet> | null = null;
function loadLeaflet() {
  leafletLoading ??= Promise.all([import("leaflet"), import("leaflet/dist/leaflet.css")]).then(([m]) => m.default ?? m);
  return leafletLoading;
}

function pinIcon(L: typeof Leaflet, color: string, big: boolean) {
  const size = big ? 26 : 18;
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<span style="display:block;width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:3px solid white;box-shadow:0 1px 4px rgba(0,0,0,.45)"></span>`,
  });
}

export function MapView({
  points,
  line,
  lineColor = "#0369a1",
  highlight,
  onPick,
  onDragEnd,
  height = 260,
  zoom = 15,
}: {
  points: MapPoint[];
  line?: [number, number][];
  lineColor?: string;
  highlight?: [number, number][]; // extra red dots, e.g. off-route positions
  onPick?: (lat: number, lng: number) => void; // click/tap on the map
  onDragEnd?: (index: number, lat: number, lng: number) => void;
  height?: number;
  zoom?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<Leaflet.Map | null>(null);
  const layer = useRef<Leaflet.LayerGroup | null>(null);
  const L = useRef<typeof Leaflet | null>(null);
  const callbacks = useRef({ onPick, onDragEnd });
  callbacks.current = { onPick, onDragEnd };
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  // Create the map once
  useEffect(() => {
    let cancelled = false;
    loadLeaflet().then((lib) => {
      if (cancelled || !box.current || map.current) return;
      L.current = lib;
      const first = points[0];
      map.current = lib.map(box.current, { scrollWheelZoom: false })
        .setView(first ? [first.latitude, first.longitude] : [-26.2041, 28.0473], zoom);
      lib.tileLayer(TILE_URL, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(map.current);
      layer.current = lib.layerGroup().addTo(map.current);
      map.current.on("click", (e: Leaflet.LeafletMouseEvent) => callbacks.current.onPick?.(e.latlng.lat, e.latlng.lng));
      setReady(true);
    }).catch(() => setFailed(true));
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Redraw markers and lines whenever they change
  const key = JSON.stringify([points, line, highlight]);
  useEffect(() => {
    const lib = L.current, m = map.current, group = layer.current;
    if (!ready || !lib || !m || !group) return;
    group.clearLayers();
    const bounds: [number, number][] = [];
    if (line && line.length > 1) {
      lib.polyline(line, { color: lineColor, weight: 4, opacity: 0.8 }).addTo(group);
      bounds.push(...line);
    }
    highlight?.forEach(([lat, lng]) => {
      lib.circleMarker([lat, lng], { radius: 6, color: COLORS.red, fillOpacity: 0.9 }).addTo(group);
    });
    points.forEach((p, i) => {
      const marker = lib.marker([p.latitude, p.longitude], {
        icon: pinIcon(lib, COLORS[p.color ?? "blue"], Boolean(p.draggable)),
        draggable: Boolean(p.draggable),
        keyboard: false,
      }).addTo(group);
      if (p.label) marker.bindTooltip(p.label);
      if (p.draggable) {
        marker.on("dragend", () => {
          const at = marker.getLatLng();
          callbacks.current.onDragEnd?.(i, at.lat, at.lng);
        });
      }
      bounds.push([p.latitude, p.longitude]);
    });
    if (bounds.length > 1) m.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
    else if (bounds.length === 1) m.setView(bounds[0], Math.max(m.getZoom(), zoom));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, key]);

  if (failed) return <p className="rounded-xl bg-slate-100 p-4 text-sm text-slate-500">The map couldn't load. Check your internet connection.</p>;
  return (
    <div className="relative isolate overflow-hidden rounded-xl border border-slate-200 bg-slate-100" style={{ height }}>
      <div ref={box} className="h-full w-full" />
      {!ready && <p className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">Loading map…</p>}
    </div>
  );
}
