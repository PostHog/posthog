import os from "node:os";
import path from "node:path";
import { defineConfig } from "drizzle-kit";

const appName =
  process.env.NODE_ENV === "production" ? "posthog-code" : "posthog-code-dev";
const userDataPath = path.join(
  os.homedir(),
  "Library",
  "Application Support",
  "@posthog",
  appName,
);

export default defineConfig({
  dialect: "sqlite",
  schema: "./src/db/schema.ts",
  out: "./src/db/migrations",
  casing: "snake_case",
  dbCredentials: {
    url: path.join(userDataPath, "posthog-code.db"),
  },
});
