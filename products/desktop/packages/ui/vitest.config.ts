import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Resolve self-package imports (`@posthog/ui/*`) to source so tests that
      // transitively load self-importing UI modules work under vitest.
      "@posthog/ui": fileURLToPath(new URL("./src", import.meta.url)),
      // `@posthog/di` exposes subpaths (`/react`, `/logger`) via a renderer
      // Vite alias, not its package `exports`; mirror that for vitest so tests
      // of `useService`-based hooks resolve.
      "@posthog/di": fileURLToPath(new URL("../di/src", import.meta.url)),
      "@posthog/host-router": fileURLToPath(
        new URL("../host-router/src", import.meta.url),
      ),
      // quill-charts' dist imports dayjs plugins without the .js extension,
      // which Vite's browser resolution accepts but vitest's Node resolution
      // rejects; map them so any test that loads quill-charts can run.
      "dayjs/plugin/customParseFormat": "dayjs/plugin/customParseFormat.js",
      "dayjs/plugin/timezone": "dayjs/plugin/timezone.js",
      "dayjs/plugin/utc": "dayjs/plugin/utc.js",
    },
  },
  test: {
    server: {
      deps: {
        // Process quill-charts through Vite instead of Node so the dayjs
        // aliases above apply to its imports too.
        inline: ["@posthog/quill-charts"],
      },
    },
    globals: true,
    ...trunkTestOptions,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
