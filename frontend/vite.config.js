import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwind from "@tailwindcss/vite";

// El proxy solo aplica en desarrollo. En el servidor, nginx sirve dist/ y
// pasa /api al backend; ahí este archivo no interviene.
export default defineConfig({
  plugins: [react(), tailwind()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8020",
        changeOrigin: true,
        // El chat llega por streaming: sin esto el proxy acumula la
        // respuesta y la entrega al final, que anula el streaming entero.
        configure: (proxy) => {
          proxy.on("proxyRes", (res) => { res.headers["cache-control"] = "no-cache"; });
        },
      },
    },
  },
});
