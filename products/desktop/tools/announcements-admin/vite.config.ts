import { readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The installed @posthog/brand release is the authority on which hoggie PNGs
// exist (metadata slugs alone 404 for variants). The dependency is pinned to
// the same version hoggiePngUrl loads from the CDN, so every name injected
// here resolves there — the images themselves are never bundled.
const require = createRequire(import.meta.url);
const hoggiePngDir = join(
  dirname(require.resolve("@posthog/brand/package.json")),
  "dist/generated/hoggies/png",
);
const hoggieFiles = readdirSync(hoggiePngDir)
  .filter((file) => file.endsWith(".png"))
  .map((file) => file.slice(0, -".png".length));

// Absolute base: the SPA fallback serves index.html on sub-routes like
// /oauth/callback, where relative asset paths would resolve to /oauth/assets.
export default defineConfig({
  base: "/",
  plugins: [react()],
  define: {
    __HOGGIE_FILES__: JSON.stringify(hoggieFiles),
  },
});
