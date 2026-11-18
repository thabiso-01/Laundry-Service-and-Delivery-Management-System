// Live selfie for driver verification (SEC-001). The photo must be taken
// with the camera now, so there is no "choose a file" option. The camera only
// works on https or localhost, and is always switched off when this closes.

import { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";
import { Button } from "./ui";

function cameraError(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (!window.isSecureContext) return "The camera only works on a secure (https) connection.";
  if (name === "NotAllowedError") return "Camera permission was refused. Allow the camera for this site in your browser settings, then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device. Use a phone or a computer with a camera.";
  if (name === "NotReadableError") return "The camera is being used by another app. Close it and try again.";
  return "Couldn't start the camera. Try again, or use another device.";
}

export function SelfieCamera({ onUse, onClose }: { onUse: (photo: File) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(true);
  const [shot, setShot] = useState<{ blob: Blob; url: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setStarting(true);
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("unsupported");
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 1280 } },
          audio: false,
        });
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        stream.current = s;
        if (video.current) {
          video.current.srcObject = s;
          await video.current.play();
        }
      } catch (e) {
        if (!cancelled) setError(cameraError(e));
      } finally {
        if (!cancelled) setStarting(false);
      }
    })();
    return () => {
      cancelled = true;
      stream.current?.getTracks().forEach((t) => t.stop()); // always switch the camera off
      stream.current = null;
    };
  }, [attempt]);

  // Free the preview image when it's replaced or the window closes
  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url); }, [shot]);

  function take() {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    // Square crop from the middle, at most 1080 px
    const side = Math.min(v.videoWidth, v.videoHeight);
    const size = Math.min(side, 1080);
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    // Mirror it, so the photo looks the same as the preview the person saw
    ctx.translate(size, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, size, size);
    canvas.toBlob((blob) => {
      if (blob) setShot({ blob, url: URL.createObjectURL(blob) });
    }, "image/jpeg", 0.9);
  }

  function use() {
    if (!shot) return;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
    onUse(new File([shot.blob], `selfie-${stamp}.jpg`, { type: "image/jpeg" }));
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="Take a selfie">
      <div className="w-full max-w-md rounded-2xl bg-surface p-4 shadow-xl sm:p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">{shot ? "Check your selfie" : "Take a selfie"}</h2>
          <button onClick={onClose} className="grid h-9 w-9 place-items-center rounded-full text-slate-500 hover:bg-slate-100" aria-label="Close">
            <Icon name="x" className="h-5 w-5" />
          </button>
        </div>

        {error ? (
          <div className="space-y-3">
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{error}</p>
            <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>Try again</Button>
          </div>
        ) : (
          <>
            <div className="relative overflow-hidden rounded-2xl bg-black">
              {/* The live video stays mounted while a photo is shown, so retaking is instant */}
              <video ref={video} className={`aspect-square w-full -scale-x-100 object-cover ${shot ? "invisible" : ""}`} playsInline muted />
              {shot && <img src={shot.url} alt="Your selfie" className="absolute inset-0 h-full w-full object-cover" />}
              {!shot && !starting && (
                <div className="pointer-events-none absolute inset-0 grid place-items-center">
                  <div className="h-[72%] w-[56%] rounded-[50%] border-4 border-white/80 shadow-[0_0_0_999px_rgb(0_0_0/0.35)]" />
                </div>
              )}
              {starting && <p className="absolute inset-0 grid place-items-center text-sm text-white">Starting camera…</p>}
            </div>
            <p className="mt-3 text-sm text-slate-600">
              {shot ? "Is your whole face clear and in focus?" : "Put your face inside the oval, in good light. No sunglasses or hat."}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {shot ? (
                <>
                  <Button icon="check" onClick={use}>Use this photo</Button>
                  <Button variant="secondary" onClick={() => setShot(null)}>Retake</Button>
                </>
              ) : (
                <Button icon="camera" size="lg" className="w-full" disabled={starting} onClick={take}>Take photo</Button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
