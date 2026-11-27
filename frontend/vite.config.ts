import {defineConfig} from "vitest/config";
import react from "@vitejs/plugin-react";

// `vite build --mode demo` (npm run build:demo) loads .env.demo (VITE_DEMO=1) and produces a
// static, read-only build for GitHub Pages that reads the JSON in demo-data/ instead of /api. It
// goes to dist-demo/ (git-ignored); the normal build keeps writing the committed bundle to
// agentscope/api/static.
export default defineConfig(({mode}) => {
  const demo = mode === "demo";
  return {
    plugins: [react()],
    base: demo ? "/AgentScope/" : "/",
    publicDir: demo ? "demo-data" : false,
    server: {
      host: true,
      port: 5173,
      proxy: {"/api": "http://127.0.0.1:8000"},
    },
    build: {
      outDir: demo ? "dist-demo" : "../agentscope/api/static",
      emptyOutDir: true,
    },
    test: {
      environment: "jsdom",
      include: ["test/**/*.test.{ts,tsx}"],
      restoreMocks: true,
    },
  };
});
