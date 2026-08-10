import type { BuildOptions, Plugin } from 'esbuild'
// Shared esbuild config for the integration-service Hono runtime.
// `build-integration-service.ts` runs it once for production;
// `dev-integration-service.ts` wraps it in `context().watch()` for the dev loop.
//
// No externals: every prod dep is pure-JS (or has a Node-target shim esbuild
// handles). Bundling everything lets the runtime image ship a single .mjs with no
// node_modules at all, which is what keeps this service's dependency surface
// auditable — see check-import-boundary.ts and check-deps-allowlist.ts.
import { resolve } from 'path'

export const integrationServiceOutfile = resolve(process.cwd(), 'dist/integration-service.mjs')
export const integrationServiceMetafile = resolve(process.cwd(), 'dist/meta.json')

// The AWS SDK's runtimeConfig statically imports the whole default credential chain, so
// esbuild would bundle SSO, shared-INI, credential_process and IMDS even though the S3
// client always gets an explicit provider (src/aws/credentials.ts) and can never reach
// them. Alias them to a stub that throws if anything ever does.
//
// This is a security control, not only a size optimisation: the service must not be able to
// authenticate silently as an EC2 instance role, or as whatever a developer last ran
// `aws sso login` against.
const UNREACHABLE_CREDENTIAL_PROVIDERS = [
    '@aws-sdk/credential-provider-sso',
    '@aws-sdk/credential-provider-ini',
    '@aws-sdk/credential-provider-process',
    '@aws-sdk/credential-provider-node',
    '@aws-sdk/credential-provider-env',
]

export function integrationServiceEsbuildOptions(opts: { dev?: boolean; extraPlugins?: Plugin[] } = {}): BuildOptions {
    return {
        entryPoints: [resolve(process.cwd(), 'src/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile: integrationServiceOutfile,
        sourcemap: true,
        external: [],
        metafile: true,
        alias: Object.fromEntries(
            UNREACHABLE_CREDENTIAL_PROVIDERS.map((name) => [
                name,
                resolve(process.cwd(), 'src/aws/unreachable-provider.ts'),
            ])
        ),
        loader: { '.json': 'json' },
        define: { 'process.env.NODE_ENV': opts.dev ? '"development"' : '"production"' },
        plugins: opts.extraPlugins ?? [],
        // Bundled CJS modules (e.g. ioredis using `require('util')`) call through to a
        // global `require`. ESM has no `require`; banner injects one.
        banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    }
}
