import { unwrapUserMessageContent } from '../logics/runStreamLogic'
import type { AttachedContextItem } from '../types/contextTypes'
import { formatPosthogContextBlock, wrapWithPosthogContext } from './posthogContextBlock'

describe('posthogContextBlock', () => {
    const keyed: AttachedContextItem = { type: 'insight', key: 'abc123', label: 'Signups' }
    const keyOnly: AttachedContextItem = { type: 'dashboard', key: 42 }
    const valueOnly: AttachedContextItem = { type: 'text', value: 'look at the error above' }

    it('renders keyed, key-only, and value-only items generically', () => {
        const block = formatPosthogContextBlock([keyed, keyOnly, valueOnly])
        expect(block).toContain('<posthog_context>')
        expect(block).toContain('</posthog_context>')
        expect(block).toContain('- insight abc123 ("Signups")')
        expect(block).toContain('- dashboard 42')
        expect(block).not.toContain('- dashboard 42 (')
        expect(block).toContain('- text: "look at the error above"')
    })

    it('returns content unchanged when there is no context', () => {
        expect(wrapWithPosthogContext('hello', [])).toBe('hello')
    })

    it('round-trips through unwrapUserMessageContent so the block is invisible on replay', () => {
        const content = 'why did signups drop?'
        const wrapped = wrapWithPosthogContext(content, [keyed, valueOnly])
        expect(wrapped).not.toBe(content)
        expect(wrapped.startsWith('<posthog_context>')).toBe(true)
        expect(unwrapUserMessageContent(wrapped)).toBe(content)
    })
})
