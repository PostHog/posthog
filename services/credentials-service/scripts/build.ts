import { build } from 'esbuild'

await build({
    // The migrate entry is its own bundle, so the server bundle does not carry the migration runner.
    entryPoints: {
        'credentials-service': 'src/index.ts',
        'credentials-service-migrate': 'src/migrate.ts',
        'credentials-service-maintenance': 'src/maintenance.ts',
    },
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

// The provider catalogue that `hogli build:projections` turns into `posthog/integrations/catalogue_generated.json`.
// It imports no npm package, so the projection can bundle it in a CI job without node_modules.
await build({
    entryPoints: ['src/catalogue.ts'],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile: 'dist/credentials-service-catalogue.mjs',
})
