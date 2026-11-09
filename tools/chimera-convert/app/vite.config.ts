import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `bun run dev` serves the UI on 5321 with the API from the Python server (5320)
export default defineConfig({
  plugins: [react()],
  server: { port: 5321, proxy: { "/api": "http://127.0.0.1:5320" } },
});
