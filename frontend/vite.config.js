import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/static/charter/",
  build: {
    outDir: "../app/static/charter",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id))
            return "react";
          if (id.includes("node_modules")) return "vendor";
        },
      },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8776" } },
});
