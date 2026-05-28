import { AssistantMessageRecord, ConversationMessage, UserMessage } from './spec'
import { lastAssistantTextPreview, totalConversationUsage } from './summarize-conversation'

function user(content: string): UserMessage {
    return { role: 'user', content, timestamp: Date.now() }
}

interface AssistantOpts {
    text?: string
    input?: number
    output?: number
    costIn?: number
    costOut?: number
}

function assistant({
    text = '',
    input = 0,
    output = 0,
    costIn = 0,
    costOut = 0,
}: AssistantOpts = {}): AssistantMessageRecord {
    return {
        role: 'assistant',
        content: text ? [{ type: 'text', text }] : [],
        api: 'anthropic-messages',
        provider: 'anthropic',
        model: 'claude-haiku-4-5',
        usage: {
            input,
            output,
            cost: { input: costIn, output: costOut, total: costIn + costOut },
        },
        timestamp: Date.now(),
    }
}

describe('lastAssistantTextPreview', () => {
    it('returns null when no assistant turn exists yet', () => {
        expect(lastAssistantTextPreview([])).toBeNull()
        expect(lastAssistantTextPreview([user('hi')])).toBeNull()
    })

    it('returns the latest assistant text block, collapsing whitespace', () => {
        const c: ConversationMessage[] = [
            user('first'),
            assistant({ text: 'first answer' }),
            user('second'),
            assistant({ text: 'second\n  answer  with   gaps' }),
        ]
        expect(lastAssistantTextPreview(c)).toBe('second answer with gaps')
    })

    it('truncates with an ellipsis past the max length', () => {
        const long = 'a'.repeat(200)
        const preview = lastAssistantTextPreview([assistant({ text: long })])
        expect(preview).toHaveLength(120)
        expect(preview!.endsWith('…')).toBe(true)
    })

    it('honors a custom max', () => {
        const preview = lastAssistantTextPreview([assistant({ text: 'hello world' })], 5)
        expect(preview).toBe('hell…')
    })

    it('skips assistant turns that have no text block (e.g. tool calls only)', () => {
        const c: ConversationMessage[] = [
            assistant({ text: 'visible reply' }),
            // No text block — only tool calls would land here in practice.
            { ...assistant({}), content: [] },
        ]
        expect(lastAssistantTextPreview(c)).toBe('visible reply')
    })
})

describe('totalConversationUsage', () => {
    it('returns all zeros for an empty conversation', () => {
        expect(totalConversationUsage([])).toEqual({
            tokens_in: 0,
            tokens_out: 0,
            cost_input: 0,
            cost_output: 0,
            cost_total: 0,
        })
    })

    it('aggregates tokens + cost across multiple assistant turns', () => {
        const c: ConversationMessage[] = [
            user('q1'),
            assistant({ text: 'a1', input: 100, output: 10, costIn: 0.001, costOut: 0.0005 }),
            user('q2'),
            assistant({ text: 'a2', input: 50, output: 5, costIn: 0.0005, costOut: 0.0003 }),
        ]
        const total = totalConversationUsage(c)
        expect(total.tokens_in).toBe(150)
        expect(total.tokens_out).toBe(15)
        expect(total.cost_input).toBeCloseTo(0.0015, 10)
        expect(total.cost_output).toBeCloseTo(0.0008, 10)
        expect(total.cost_total).toBeCloseTo(0.0023, 10)
    })

    it('ignores user / toolResult messages and assistant turns missing usage', () => {
        const noUsage = assistant({ text: 'no-usage reply' })
        noUsage.usage = undefined
        const c: ConversationMessage[] = [
            user('q'),
            noUsage,
            assistant({ text: 'counted reply', input: 7, output: 1, costIn: 0, costOut: 0 }),
        ]
        const total = totalConversationUsage(c)
        expect(total.tokens_in).toBe(7)
        expect(total.tokens_out).toBe(1)
    })
})
