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
    },
  },
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
