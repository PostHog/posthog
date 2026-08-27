const userAgent = process.env.npm_config_user_agent ?? "";

if (userAgent.startsWith("pnpm/")) {
  process.exit(0);
}

console.error(
  [
    "This repository must be installed with pnpm.",
    "Use `pnpm install` so the workspace minimumReleaseAge policy and exclusions are applied consistently.",
  ].join("\n"),
);

process.exit(1);
