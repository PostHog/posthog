// The Hono and worker entry points import `*.md`, `*.html`, and `*.yaml` files as raw
// text (esbuild inlines them via its `text` loader at build time; wrangler via a `Text`
// rule). Vitest's default loader rejects those as JS, so every Node-pool vitest config
// registers this transform that stringifies their contents. The workers-pool project
// has its own transform stack and doesn't need it.
export const textLoader = {
    name: 'text-loader',
    transform(code: string, id: string): { code: string; map: null } | undefined {
        if (id.endsWith('.md') || id.endsWith('.html') || id.endsWith('.yaml')) {
            return {
                code: `export default ${JSON.stringify(code)}`,
                map: null,
            }
        }
        return undefined
    },
}
