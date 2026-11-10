import { build } from 'esbuild'

await build({
    entryPoints: ['src/index.ts'],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile: 'dist/credentials-service.mjs',
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
