/**
 * Unit tests for compileTypedTool — the AST shape check + esbuild compile
 * pipeline that runs inside the typed `PUT /tools/:id` endpoint.
 *
 * The test split:
 *   - Happy path: valid source compiles to CJS exports.
 *   - Shape failures: every distinct AST-detected error has a parameterised
 *     case asserting the error kind + a fragment of the message.
 *   - Parse failures: TS syntax errors surface as ast_no_default_export
 *     (the parser produces a malformed tree that still completes; the
 *     "no default" check is what trips).
 *   - Async smoke: the function is async; awaiting works and returns the
 *     expected shape.
 *
 * The compiler API parses without type-checking, so this is genuinely fast
 * (~10ms per call locally) and the cases stay tight.
 */

import { compileTypedTool } from './compile-custom-tools'

const GOOD = `
export default {
    actions: {
        default: async (args: { name?: string }) => ({ greeting: 'hello ' + args.name }),
    },
}
`.trim()

describe('compileTypedTool', () => {
    it('compiles a known-good source.ts to CJS', async () => {
        const r = await compileTypedTool({ tool_id: 'greet', source: GOOD })
        expect(r.ok).toBe(true)
        expect(r.errors).toEqual([])
        expect(r.compiled_js).toBeTruthy()
        // CJS exports — esbuild defaults to `module.exports.default = ...` or
        // `exports.default = ...` depending on the source shape. Either is fine.
        expect(r.compiled_js!).toMatch(/exports/)
        expect(r.compiled_js!).not.toMatch(/^export default/m)
    })

    it('accepts string-keyed actions ({ "default": fn })', async () => {
        const src = `
        export default {
            actions: {
                "default": async () => ({ ok: true }),
            },
        }
        `.trim()
        const r = await compileTypedTool({ tool_id: 'strkey', source: src })
        expect(r.ok).toBe(true)
    })

    it.each([
        {
            label: 'bare function default — the historical concierge foot-gun',
            source: 'export default async function run() { return {} }',
            kind: 'ast_default_not_object',
            fragment: 'bare function',
        },
        {
            label: 'arrow-fn default',
            source: 'export default async () => ({})',
            kind: 'ast_default_not_object',
            fragment: 'bare function',
        },
        {
            label: 'dynamic factory call default',
            source: 'function make() { return { actions: { default: () => ({}) } } }\nexport default make()',
            kind: 'ast_dynamic_export',
            fragment: 'statically declared',
        },
        {
            label: 'identifier reference default',
            source: 'const tool = { actions: { default: () => ({}) } }\nexport default tool',
            kind: 'ast_dynamic_export',
            fragment: 'statically declared',
        },
        {
            label: 'object missing `actions`',
            source: 'export default { id: "x", run: async () => ({}) }',
            kind: 'ast_missing_actions',
            fragment: 'missing required `actions`',
        },
        {
            label: '`actions` is an array',
            source: 'export default { actions: [] }',
            kind: 'ast_actions_not_object',
            fragment: 'must be an object literal',
        },
        {
            label: '`actions` present but no `default` key',
            source: 'export default { actions: { run: async () => ({}) } }',
            kind: 'ast_missing_default_action',
            fragment: '`actions.default` is required',
        },
        {
            label: '`actions.default` is a string',
            source: 'export default { actions: { default: "not a function" } }',
            kind: 'ast_default_action_not_callable',
            fragment: '`actions.default` must be a function',
        },
        {
            label: '`actions.default` is a number',
            source: 'export default { actions: { default: 42 } }',
            kind: 'ast_default_action_not_callable',
            fragment: '`actions.default` must be a function',
        },
        {
            label: 'no export default at all',
            source: 'function foo() { return 1 }',
            kind: 'ast_no_default_export',
            fragment: 'no `export default` found',
        },
        {
            label: 'multiple export defaults',
            source: 'export default { actions: { default: () => ({}) } }\nexport default { actions: { default: () => ({}) } }',
            kind: 'ast_no_default_export',
            fragment: 'exactly one',
        },
    ])('rejects shape mismatch: $label', async ({ source, kind, fragment }) => {
        const r = await compileTypedTool({ tool_id: 'bad', source })
        expect(r.ok).toBe(false)
        expect(r.compiled_js).toBeUndefined()
        expect(r.errors).not.toEqual([])
        expect(r.errors[0].kind).toBe(kind)
        expect(r.errors[0].message).toContain(fragment)
    })

    it('the AST check tolerates `as Type` casts on the default export', async () => {
        const src = `
        export default {
            actions: {
                default: (async (args: any) => ({ ok: true })) as any,
            },
        } as const
        `.trim()
        const r = await compileTypedTool({ tool_id: 'cast', source: src })
        expect(r.ok).toBe(true)
    })

    it('reports a TS syntax error via the AST check (no esbuild call)', async () => {
        // esbuild would also reject this, but the AST step catches it first
        // — the parser produces an incomplete tree and the no-default check
        // fires.
        const r = await compileTypedTool({
            tool_id: 'bad',
            source: 'export default async function run( { return {} }',
        })
        expect(r.ok).toBe(false)
        // The exact kind depends on what TypeScript's recovery parser
        // managed to assemble; either ast_no_default_export (if the parser
        // gave up) or ast_default_not_object / ast_default_action_not_callable.
        // Just confirm we got *some* AST-level error.
        expect(r.errors[0].kind).toMatch(/^ast_/)
    })

    it('records a 1-based line number on detected errors', async () => {
        const src = `
// header comment line 1
const x = 1
export default async function run() { return {} }
        `.trim()
        const r = await compileTypedTool({ tool_id: 'pos', source: src })
        expect(r.ok).toBe(false)
        expect(r.errors[0].line).toBeGreaterThan(0)
        expect(r.errors[0].column).toBeGreaterThan(0)
    })
})
