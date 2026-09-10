import { defineConfig, type Options } from "tsup";

export function defineLibPackage(overrides: Options = {}) {
  return defineConfig({
    entry: ["src/index.ts"],
    format: ["esm"],
    dts: true,
    sourcemap: true,
    clean: true,
    splitting: false,
    outDir: "dist",
    target: "es2022",
    ...overrides,
  });
}
