import { getNativeTool, hasNativeTool, listNativeTools } from './registry'

describe('native tool registry', () => {
    it('exposes expected tools by id', () => {
        const ids = listNativeTools().map((t) => t.id)
        expect(ids).toEqual(
            expect.arrayContaining([
                'posthog.query.v1',
                'posthog.persons.search.v1',
                'slack.post_message.v1',
                'slack.update_message.v1',
                'slack.react.v1',
                'web.fetch.v1',
                'web.search.v1',
                'meta.ask_for_input.v1',
                'meta.end_session.v1',
                'meta.emit_event.v1',
            ])
        )
    })

    it('getNativeTool returns the tool', () => {
        const t = getNativeTool('posthog.query.v1')
        expect(t.id).toBe('posthog.query.v1')
        expect(t.schema.description).toMatch(/HogQL/)
    })

    it('getNativeTool throws on unknown id', () => {
        expect(() => getNativeTool('posthog.query.v999')).toThrow(/unknown native tool/)
    })

    it('hasNativeTool reflects availability', () => {
        expect(hasNativeTool('slack.post_message.v1')).toBe(true)
        expect(hasNativeTool('slack.post_message.v99')).toBe(false)
    })

    it("catalog entries don't expose the run function", () => {
        const entry = listNativeTools()[0]
        expect('run' in entry).toBe(false)
    })

    it('every tool has all required schema fields', () => {
        for (const t of listNativeTools()) {
            expect(t.schema.description.length).toBeGreaterThan(0)
            expect(t.schema.args).not.toBeUndefined()
            expect(t.schema.returns).not.toBeUndefined()
            expect(t.schema.requires).toEqual(
                expect.objectContaining({ integrations: expect.any(Array), scopes: expect.any(Array) })
            )
            expect(['cheap', 'medium', 'expensive']).toContain(t.schema.cost_hint)
        }
    })
})
