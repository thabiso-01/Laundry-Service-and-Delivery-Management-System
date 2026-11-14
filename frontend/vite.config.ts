import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";

// `npm run dev:phone` serves over https on your network so phones can use the
// camera (browsers only allow it on https or localhost). Accept the
// self-signed certificate warning once on the phone.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss(), ...(mode === "phone" ? [basicSsl()] : [])],
  server: {
    port: 5173,
    host: mode === "phone" ? true : undefined,
    // Forward /api calls to FastAPI so the browser sees one origin in dev
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
}));
