import { build } from 'esbuild'

await build({
    // The migrate entry is its own bundle, so the server bundle does not carry the migration runner.
    entryPoints: { 'credentials-service': 'src/index.ts', 'credentials-service-migrate': 'src/migrate.ts' },
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outdir: 'dist',
    outExtension: { '.js': '.mjs' },
    sourcemap: true,
    // Bundled CJS deps (pino) call a global `require`, which ESM does not have.
    banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
})
