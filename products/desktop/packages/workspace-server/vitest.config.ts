import { defineConfig } from "vitest/config";
import { trunkTestOptions } from "../../vitest.config.base";

export default defineConfig({
  test: {
    globals: true,
    ...trunkTestOptions,
    environment: "node",
    setupFiles: ["./src/test/saved-gateway-listing.ts"],
    include: ["src/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],
  },
});
