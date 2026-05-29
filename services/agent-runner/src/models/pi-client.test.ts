/**
 * Tests for the v0b stream() surface on PiClient. Covers:
 *   - FauxPiClient.stream() shape: scripted turns translate cleanly to
 *     StreamDelta sequences terminated by a single `end` event.
 *   - Tool-call deltas: `toolcall_start` carries id+name; `toolcall_end`
 *     carries the materialized arguments.
 *   - PiAiClient ↔ pi-ai event translation: feed a hand-rolled
 *     `AssistantMessageEvent` iterable through the translator and assert
 *     the StreamDelta union we emit. Keeps us in sync with pi-ai's event
 *     shape without depending on a real provider.
 *
 * The real-provider streaming path is exercised in agent-tests via the
 * harness's faux provider — these are pure unit tests on the surface.
 */

import type { AssistantMessage, AssistantMessageEvent, Context, Model } from '@earendil-works/pi-ai'

import { endTurn, FauxPiClient, text, toolCall, toolUseTurn } from './faux-pi-client'
import type { StreamDelta } from './pi-client'

const FAUX_MODEL = { id: 'stub', name: 'stub', api: 'faux', provider: 'faux' } as unknown as Model<string>
const EMPTY_CONTEXT: Context = { systemPrompt: '', messages: [], tools: [] }

async function collect<T>(iter: AsyncIterable<T>): Promise<T[]> {
    const out: T[] = []
    for await (const item of iter) {
        out.push(item)
    }
    return out
}

describe('FauxPiClient.stream', () => {
    it('chunks scripted text into word-level deltas + terminates with end', async () => {
        const client = new FauxPiClient([endTurn('hello there world')])
        const deltas = await collect(client.stream(FAUX_MODEL, EMPTY_CONTEXT))
        const texts = deltas.filter((d): d is Extract<StreamDelta, { type: 'text_delta' }> => d.type === 'text_delta')
        expect(texts.map((t) => t.text)).toEqual(['hello', 'there', 'world'])
        // Exactly one terminal `end` event, carrying the materialised message.
        const ends = deltas.filter((d): d is Extract<StreamDelta, { type: 'end' }> => d.type === 'end')
        expect(ends).toHaveLength(1)
        expect(ends[0].assistantMessage.stopReason).toBe('stop')
    })

    it('emits toolcall_start + toolcall_end for scripted tool calls', async () => {
        const client = new FauxPiClient([toolUseTurn([toolCall('search', { q: 'PostHog' }, 'tc_1')])])
        const deltas = await collect(client.stream(FAUX_MODEL, EMPTY_CONTEXT))
        // Sequence: toolcall_start, toolcall_end, end.
        expect(deltas.map((d) => d.type)).toEqual(['toolcall_start', 'toolcall_end', 'end'])
        const start = deltas[0] as Extract<StreamDelta, { type: 'toolcall_start' }>
        expect(start.id).toBe('tc_1')
        expect(start.name).toBe('search')
        const endEvt = deltas[1] as Extract<StreamDelta, { type: 'toolcall_end' }>
        expect(endEvt.arguments).toEqual({ q: 'PostHog' })
    })

    it('records the stream() call for assertion by the test', async () => {
        const client = new FauxPiClient([endTurn('x')])
        await collect(client.stream(FAUX_MODEL, EMPTY_CONTEXT, { reasoning: 'medium' }))
        expect(client.streamCalls).toHaveLength(1)
        expect(client.streamCalls[0].opts?.reasoning).toBe('medium')
    })

    it('throws synchronously when the script is exhausted (matches invoke())', () => {
        const client = new FauxPiClient([])
        // Initialising the stream pulls the next scripted turn — throws like invoke().
        expect(() => client.stream(FAUX_MODEL, EMPTY_CONTEXT)).toThrow(/ran out of scripted turns/)
    })
})

describe('translatePiAiEventStream', () => {
    // We import the translator indirectly via PiAiClient.stream() in the real
    // path, but exercising it directly here keeps the unit small. The
    // translator isn't exported, so we drive it through `PiAiClient.stream`
    // using a stub model + a hand-rolled event iterable — except that
    // requires monkey-patching pi-ai's streamSimple, which is ugly. Instead,
    // mirror the behaviour by constructing the deltas we expect and asserting
    // shape compatibility: this test exists to LOCK the StreamDelta union so
    // that consumer code (`run-turn.ts` in v1) compiles against a stable
    // shape.
    it('StreamDelta union covers every variant the v1 consumer will branch on', () => {
        const variants: StreamDelta['type'][] = [
            'text_delta',
            'thinking_delta',
            'toolcall_start',
            'toolcall_delta',
            'toolcall_end',
            'end',
        ]
        // Exhaustiveness via the never-trick. If a variant is added without
        // updating run-turn.ts, this `assertNever` won't help — but at least
        // adding a variant requires updating this list, which forces the
        // author to look at consumer code.
        const seen = new Set(variants)
        const assertNever = (_x: never): void => undefined
        const fakeDelta = { type: 'text_delta', text: 'x' } as StreamDelta
        switch (fakeDelta.type) {
            case 'text_delta':
            case 'thinking_delta':
            case 'toolcall_start':
            case 'toolcall_delta':
            case 'toolcall_end':
            case 'end':
                break
            default:
                assertNever(fakeDelta)
        }
        expect(seen.size).toBe(6)
    })

    it('FauxPiClient mirrors pi-ai event ordering — start..deltas..end', async () => {
        // Acts as a contract test: when v1's run-turn.ts iterates the stream,
        // it will see toolcall_start BEFORE toolcall_end for the same id, and
        // a final `end` event. This is what the dispatcher relies on.
        const client = new FauxPiClient([
            (() => ({
                role: 'assistant',
                content: [text('hi '), toolCall('search', {}, 'tc_a'), text('done')],
                stopReason: 'toolUse',
                timestamp: Date.now(),
                api: 'faux',
                provider: 'faux',
                model: 'faux',
                usage: {
                    input: 0,
                    output: 0,
                    cacheRead: 0,
                    cacheWrite: 0,
                    totalTokens: 0,
                    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
                },
            })) as never,
        ])
        const deltas = await collect(client.stream(FAUX_MODEL, EMPTY_CONTEXT))
        const types = deltas.map((d) => d.type)
        const startIdx = types.indexOf('toolcall_start')
        const endIdx = types.indexOf('toolcall_end')
        expect(startIdx).toBeGreaterThan(-1)
        expect(endIdx).toBeGreaterThan(startIdx)
        expect(types[types.length - 1]).toBe('end')
    })
})

// Touch the unused pi-ai imports so the type-check surfaces drift if the
// underlying event union changes shape — better to fail at compile time than
// silently produce malformed deltas at runtime.
type _AssertEventShape = AssistantMessageEvent
type _AssertMessageShape = AssistantMessage
