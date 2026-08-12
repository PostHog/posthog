#!/usr/bin/env node
/**
 * Point the desktop app's analytics + feature-flag client at your LOCAL PostHog
 * (localhost:8010) for dev. Code reads feature flags through posthog-js, which
 * is configured by the `VITE_POSTHOG_*` vars in `.env` — by default these point
 * at PostHog's internal analytics instance, so flags you sync locally (e.g.
 * `manage.py sync_feature_flags` → `agent-platform`) never resolve in dev. This
 * rewrites those vars to your local instance so synced flags take effect.
 *
 * Note: this is the analytics/flags client only — separate from the data API
 * the app calls per logged-in region (the "Dev" region already points at
 * localhost:8010; see docs/LOCAL-DEVELOPMENT.md).
 *
 * Usage:
 *   node scripts/use-local-posthog.mjs                  # auto-fetch project key from ../posthog
 *   node scripts/use-local-posthog.mjs phc_xxx          # pass the project key explicitly
 *   LOCAL_POSTHOG_PROJECT_KEY=phc_xxx node scripts/use-local-posthog.mjs
 *   POSTHOG_DIR=/path/to/posthog node scripts/use-local-posthog.mjs
 *   LOCAL_POSTHOG_HOST=http://localhost:8010 node scripts/use-local-posthog.mjs
 *
 * Restart the dev server (`pnpm dev`) afterwards to pick up the new env.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const envPath = join(repoRoot, ".env");
const host = process.env.LOCAL_POSTHOG_HOST || "http://localhost:8010";

function fail(message) {
  console.error(`\n✗ ${message}\n`);
  process.exit(1);
}

/** Project API key from arg/env, else read it from a local PostHog checkout. */
function resolveProjectKey() {
  const explicit = (
    process.argv[2] || process.env.LOCAL_POSTHOG_PROJECT_KEY
  )?.trim();
  if (explicit) return explicit;

  const posthogDir =
    process.env.POSTHOG_DIR || resolve(repoRoot, "..", "posthog");
  if (!existsSync(join(posthogDir, "manage.py"))) {
    fail(
      `No project key given and no PostHog checkout at ${posthogDir}.\n` +
        `  • Pass it: node scripts/use-local-posthog.mjs <phc_token>\n` +
        `  • Or point at your checkout: POSTHOG_DIR=/path/to/posthog node scripts/use-local-posthog.mjs\n` +
        `  • Find the key at ${host} → Settings → Project → "Project API key".`,
    );
  }

  const py =
    "from posthog.models import Team; t=Team.objects.order_by('id').first(); print(t.api_token if t else '')";
  // `flox activate` provides the Django env on PostHog's local setup; fall back
  // to a bare `python` for other environments.
  const attempts = [
    ["flox", ["activate", "--", "python", "manage.py", "shell", "-c", py]],
    ["python", ["manage.py", "shell", "-c", py]],
  ];
  for (const [cmd, args] of attempts) {
    try {
      const out = execFileSync(cmd, args, {
        cwd: posthogDir,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      });
      const token = out
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l.startsWith("phc_"))
        .pop();
      if (token) return token;
    } catch {
      // Try the next runner.
    }
  }
  fail(
    `Couldn't read the project key from ${posthogDir}.\n` +
      `Pass it explicitly: node scripts/use-local-posthog.mjs <phc_token>`,
  );
}

function upsertEnv(content, key, value) {
  const line = `${key}=${value}`;
  const re = new RegExp(`^${key}=.*$`, "m");
  if (re.test(content)) return content.replace(re, line);
  const prefix =
    content === "" || content.endsWith("\n") ? content : `${content}\n`;
  return `${prefix}${line}\n`;
}

const projectKey = resolveProjectKey();
if (!projectKey.startsWith("phc_")) {
  fail(`That doesn't look like a project key (expected phc_…): ${projectKey}`);
}

let env = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
env = upsertEnv(env, "VITE_POSTHOG_API_HOST", host);
env = upsertEnv(env, "VITE_POSTHOG_UI_HOST", host);
env = upsertEnv(env, "VITE_POSTHOG_API_KEY", projectKey);
writeFileSync(envPath, env);

console.log(`✓ Pointed the desktop app's flags/analytics at local PostHog.`);
console.log(`  VITE_POSTHOG_API_HOST=${host}`);
console.log(`  VITE_POSTHOG_UI_HOST=${host}`);
console.log(`  VITE_POSTHOG_API_KEY=${projectKey.slice(0, 8)}… (project key)`);
console.log(`\nRestart the dev server (pnpm dev) to pick up the new env.`);
