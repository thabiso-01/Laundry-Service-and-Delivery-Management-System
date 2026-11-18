import { useEffect, useState } from "react";
import { Icon } from "./icons";

// Light/dark switch. The choice is remembered on this device; until someone
// picks, the app follows the phone or computer's own setting (public/theme.js).

const KEY = "lc-theme";

function apply(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0b1121" : "#4361ee");
}

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  // Follow the device setting while the user hasn't chosen
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      let saved: string | null = null;
      try { saved = localStorage.getItem(KEY); } catch { /* storage blocked */ }
      if (!saved) { apply(e.matches); setDark(e.matches); }
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  function toggle() {
    const next = !dark;
    apply(next);
    setDark(next);
    try { localStorage.setItem(KEY, next ? "dark" : "light"); } catch { /* storage blocked */ }
  }

  const label = dark ? "Switch to light mode" : "Switch to dark mode";
  return (
    <button type="button" onClick={toggle} aria-label={label} title={label}
      className="grid h-10 w-10 place-items-center rounded-full text-slate-600 hover:bg-slate-100 hover:text-slate-900">
      <Icon name={dark ? "sun" : "moon"} className="h-5 w-5" />
    </button>
  );
}
