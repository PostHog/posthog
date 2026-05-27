import { SimpleCompiler } from './compile'

const SOURCE = `
defineTool({
    id: "fetch-acme-account",
    description: "Look up an Acme CRM account by domain.",
    inputs: [
        { name: "ACME_API_KEY", secret: true, description: "Acme API key" },
    ],
    actions: {
        default: async (args, ctx) => {
            const res = await ctx.http.fetch("https://api.acme.com/accounts")
            return res.json()
        },
        search: async (args, ctx) => {
            return {}
        },
    },
})
`

describe('SimpleCompiler', () => {
    it('extracts id and description', async () => {
        const c = new SimpleCompiler()
        const out = await c.compile(SOURCE, 'fallback')
        expect(out.schemaJson.id).toBe('fetch-acme-account')
        expect(out.schemaJson.description).toMatch(/Acme CRM/)
    })

    it('extracts action names', async () => {
        const c = new SimpleCompiler()
        const out = await c.compile(SOURCE, 'x')
        const names = out.schemaJson.actions.map((a) => a.name).sort()
        expect(names).toContain('default')
        expect(names).toContain('search')
    })

    it('extracts inputs with secret flag', async () => {
        const c = new SimpleCompiler()
        const out = await c.compile(SOURCE, 'x')
        expect(out.inputsJson).toEqual([{ name: 'ACME_API_KEY', secret: true, description: 'Acme API key' }])
    })

    it('falls back when no actions block', async () => {
        const c = new SimpleCompiler()
        const out = await c.compile(`defineTool({ id: "noop", description: "x" })`, 'noop')
        expect(out.schemaJson.actions[0].name).toBe('default')
    })
})
