import { build } from 'esbuild'

await build({
    entryPoints: ['src/index.ts'],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile: 'dist/integration-service.mjs',
    sourcemap: true,
    // Bundled CJS deps (pino) call a global `require`, which ESM does not have.
    banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
})
