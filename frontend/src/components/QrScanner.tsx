// Camera QR scanning for bag labels (SEC-011).
//
// Uses the browser's built-in BarcodeDetector where available (Chrome on
// Android), otherwise decodes frames with jsQR, which works everywhere –
// including iPhone Safari. The camera only works on https or localhost.
// Only LaundryConnect bag codes are accepted, so a stray QR code nearby
// (a poster, another app) is ignored.

import { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";
import { Button } from "./ui";

export const BAG_CODE = /^LCQ1\.[A-Z0-9.-]+$/i;

interface Detector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

function nativeDetector(): Detector | null {
  const Ctor = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
  try {
    return Ctor ? new Ctor({ formats: ["qr_code"] }) : null;
  } catch {
    return null;
  }
}

// jsQR (~140 kB) is only downloaded the first time someone opens the scanner
type JsQR = typeof import("jsqr").default;
let jsQRLoading: Promise<JsQR> | null = null;
const loadJsQR = () => (jsQRLoading ??= import("jsqr").then((m) => m.default));

async function decodeCanvas(canvas: HTMLCanvasElement): Promise<string | null> {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  const jsQR = await loadJsQR();
  const { width, height } = canvas;
  const image = ctx.getImageData(0, 0, width, height);
  return jsQR(image.data, width, height, { inversionAttempts: "attemptBoth" })?.data ?? null;
}

// Fallback for phones where live video is blocked: decode a photo instead
async function decodeFile(file: File): Promise<string | null> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  // Shrink big photos: faster, and jsQR copes better at moderate sizes
  const scale = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height));
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return decodeCanvas(canvas);
}

function cameraError(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (!window.isSecureContext) return "The camera only works on a secure (https) connection. Take a photo instead, or type the code.";
  if (name === "NotAllowedError") return "Camera permission was refused. Allow it in your browser settings, or take a photo instead.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError") return "The camera is being used by another app.";
  return "Couldn't start the camera. Take a photo instead, or type the code.";
}

export function QrScanner({ onResult, onClose }: { onResult: (code: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [starting, setStarting] = useState(true);
  const done = useRef(false);

  const accept = (value: string | null) => {
    if (done.current || !value) return false;
    const code = value.trim();
    if (!BAG_CODE.test(code)) {
      setHint("That isn't a LaundryConnect bag label. Point the camera at the label on the bag.");
      return false;
    }
    done.current = true;
    navigator.vibrate?.(80);
    onResult(code.toUpperCase());
    return true;
  };

  useEffect(() => {
    let stream: MediaStream | null = null;
    let timer: number | null = null;
    let busy = false;
    const detector = nativeDetector();
    if (!detector) void loadJsQR(); // start downloading while the camera warms up

    const tick = async () => {
      const v = video.current, c = canvas.current;
      if (busy || done.current || !v || !c || v.readyState < 2) return;
      busy = true;
      try {
        if (detector) {
          const found = await detector.detect(v);
          for (const f of found) if (accept(f.rawValue)) return;
        } else {
          // Decode the centre square of the frame: faster and ignores clutter at the edges
          const side = Math.min(v.videoWidth, v.videoHeight);
          const size = Math.min(side, 640);
          c.width = size;
          c.height = size;
          c.getContext("2d")!.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, size, size);
          accept(await decodeCanvas(c));
        }
      } catch {
        /* a frame that can't be read – try the next one */
      } finally {
        busy = false;
      }
    };

    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera API");
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        timer = window.setInterval(() => void tick(), 200);
      } catch (e) {
        setError(cameraError(e));
      } finally {
        setStarting(false);
      }
    })();

    return () => {
      if (timer) clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop()); // always switch the camera off
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-label="Scan bag label">
      <div className="w-full max-w-md rounded-2xl bg-surface p-4 shadow-xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Scan the bag label</h2>
          <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Close">✕</button>
        </div>
        {!error && (
          <div className="relative overflow-hidden rounded-xl bg-black">
            <video ref={video} className="aspect-square w-full object-cover" playsInline muted />
            <div className="pointer-events-none absolute inset-[15%] rounded-xl border-4 border-white/80" />
            {starting && <p className="absolute inset-0 flex items-center justify-center text-sm text-white">Starting camera…</p>}
          </div>
        )}
        <canvas ref={canvas} className="hidden" />
        {error && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{error}</p>}
        {hint && !error && <p className="mt-2 text-sm text-amber-700">{hint}</p>}
        {!error && !hint && <p className="mt-2 text-sm text-slate-600">Hold the QR code inside the square.</p>}
        <label className="mt-3 block cursor-pointer rounded-lg border border-dashed border-slate-300 p-3 text-center text-sm text-brand-700 hover:bg-brand-50">
          <span className="inline-flex items-center gap-2"><Icon name="camera" className="h-4 w-4" /> Take a photo of the label instead</span>
          <input type="file" accept="image/*" capture="environment" className="hidden" onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setHint(null);
            const value = await decodeFile(file).catch(() => null);
            if (!value) setHint("Couldn't find a QR code in that photo. Try again closer, with good light.");
            else accept(value);
          }} />
        </label>
      </div>
    </div>
  );
}

// A text field with a "Scan" button: scan with the camera, or type / paste the code
export function BagCodeField({ value, onChange, label = "Bag label code" }: {
  value: string;
  onChange: (code: string) => void;
  label?: string;
}) {
  const [scanning, setScanning] = useState(false);
  const valid = !value || BAG_CODE.test(value.trim());
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="bag-code">{label}</label>
      <div className="flex gap-2">
        <input id="bag-code" value={value} onChange={(e) => onChange(e.target.value)} placeholder="LCQ1.LC-…" autoComplete="off"
          className="block h-10 min-w-0 flex-1 rounded-lg border-0 bg-surface px-3 font-mono text-sm shadow-sm ring-1 ring-inset ring-slate-300 outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600" />
        <Button type="button" icon="camera" onClick={() => setScanning(true)}>Scan</Button>
      </div>
      {value && valid
        ? <p className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-emerald-700"><Icon name="checkCircle" className="h-3.5 w-3.5" /> Code captured</p>
        : <p className={`mt-1.5 text-xs ${valid ? "text-slate-500" : "text-rose-700"}`}>
            {valid ? "Scan the QR on the bag, or type the code printed under it." : "That doesn't look like a LaundryConnect bag code."}
          </p>}
      {scanning && <QrScanner onClose={() => setScanning(false)} onResult={(code) => { onChange(code); setScanning(false); }} />}
    </div>
  );
}
