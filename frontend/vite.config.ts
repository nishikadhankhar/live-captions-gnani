import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import basicSsl from "@vitejs/plugin-basic-ssl";

// Phones only allow the microphone on https (or localhost). For a demo on the venue
// Wi-Fi run `HTTPS=1 npm run dev -- --host` and accept the self-signed certificate once.
const https = process.env.HTTPS === "1";
const backend = process.env.BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss(), ...(https ? [basicSsl()] : [])],
  server: {
    port: 5173,
    // Phones reach the laptop through a Cloudflare quick tunnel (demo.sh).
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist" },
});
