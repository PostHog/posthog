import { execFileSync } from "node:child_process";

execFileSync("pnpm", process.argv.slice(2), { stdio: "inherit", shell: true });
