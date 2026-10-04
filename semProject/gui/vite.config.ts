// Vite: the dev server and bundler for the React app.
//
//   npm run dev     http://localhost:5173 with instant reload while editing.
//                   Calls to /api are forwarded to the Python server, which
//                   must be running too (uv run semProject/main.py gui).
//   npm run build   writes the finished app to dist/, which the Python
//                   server then serves itself at http://127.0.0.1:8765.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
