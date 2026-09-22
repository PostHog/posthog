import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "node",
    // Hooks in this package build real git repositories with child processes,
    // which outruns the 10s default when CI runs every package suite at once.
    hookTimeout: 30_000,
    include: ["src/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
