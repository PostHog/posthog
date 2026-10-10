import { build } from 'esbuild'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

/** Bundle the same tool factories as MCP, with a local SDK host instead of a protocol server. */
export async function buildSdkHandlers(repoRoot, destination) {
    const virtual = {
        '@/lib/env': 'export const env = {}',
        '@/resources/ui-apps': 'export const withUiApp = (_key, tool) => tool',
        '@/hono/metrics': `const counter = { inc() {} }; export const confirmedActionExecutesTotal = counter, confirmedActionPreparesTotal = counter, confirmedActionRefusalsTotal = counter`,
        '@/lib/posthog': `const noop = () => {}; const client = { capture: noop, captureException: noop, captureImmediate: async () => {}, flush: async () => {}, getFeatureFlag: async () => undefined, getFeatureFlags: async () => ({}) }; export const getPostHogClient = () => client; export const getMCPServerBuild = () => undefined`,
    }
    await fs.mkdir(path.dirname(destination), { recursive: true })
    await build({
        entryPoints: [path.join(repoRoot, 'services/mcp/sdk/host.ts')],
        outfile: destination,
        absWorkingDir: repoRoot,
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        minify: true,
        legalComments: 'eof',
        tsconfig: path.join(repoRoot, 'services/mcp/tsconfig.json'),
        banner: {
            js: "import { createRequire as sdkCreateRequire } from 'node:module'; const require = sdkCreateRequire(import.meta.url);",
        },
        plugins: [
            {
                name: 'sdk-host',
                setup(builder) {
                    builder.onResolve({ filter: /^@\// }, ({ path: name }) => {
                        if (name === '@/tools/confirmed-action-registry') {
                            return { path: path.join(repoRoot, 'services/mcp/sdk/host-state.ts') }
                        }
                        if (name === '@/lib/cache/MemoryCache') {
                            return { path: path.join(repoRoot, 'services/mcp/sdk/client-cache.ts') }
                        }
                        if (Object.hasOwn(virtual, name)) {
                            return { path: name, namespace: 'sdk-host' }
                        }
                        if (name === '@/lib/posthog/client' || name === '@/lib/posthog/index') {
                            return { path: '@/lib/posthog', namespace: 'sdk-host' }
                        }
                    })
                    builder.onResolve({ filter: /^@shared\/parser_recipe_examples.yaml$/ }, () => ({
                        path: path.join(
                            repoRoot,
                            'products/ai_observability/backend/prompts/parser_recipe_examples.yaml'
                        ),
                    }))
                    builder.onLoad({ filter: /.*/, namespace: 'sdk-host' }, ({ path: name }) => ({
                        contents: virtual[name],
                    }))
                    builder.onLoad({ filter: /\.ya?ml$/ }, async ({ path: file }) => ({
                        contents: `export default ${JSON.stringify(await fs.readFile(file, 'utf8'))}`,
                        loader: 'js',
                    }))
                },
            },
        ],
    })
    await fs.writeFile(
        destination.replace(/\.mjs$/, '.d.mts'),
        `import type { SharedToolSession, SharedToolSessionOptions } from '../runtime/shared-tools.js'\nexport declare function createToolSession(options: SharedToolSessionOptions): SharedToolSession\n`
    )
    return (await import(`${pathToFileURL(destination)}?generation=${Date.now()}`)).getToolSchemas()
}
