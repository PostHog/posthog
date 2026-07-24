import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createExecTool, formatInvalidJsonInput } from '@/tools/exec'
import { type Context, type Tool, type ZodObjectAny } from '@/tools/types'

function makeCaptureTool(): { tool: Tool<ZodObjectAny>; captured: () => unknown } {
    let last: unknown
    const tool: Tool<ZodObjectAny> = {
        name: 'capture-tool',
        title: 'Capture tool',
        description: 'captures its input',
        schema: z.object({ content: z.string(), key: z.string().optional() }),
        scopes: [],
        annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
        handler: async (_ctx, args) => {
            last = args
            return { ok: true }
        },
    }
    return { tool, captured: () => last }
}

const mockContext = { getDistinctId: async () => 'x' } as unknown as Context

describe('exec call JSON body', () => {
    // Guards the reported symptom: `call`/`call --json` was said to reject valid JSON
    // containing multi-byte UTF-8 or a long string. The in-process parser must accept
    // both — a regression here (e.g. a byte-length cap or chunk-boundary split) would
    // break exactly these payloads.
    it.each([
        { name: 'multi-byte UTF-8 (em-dash)', input: { content: 'foo — bar' } },
        {
            name: 'long string with escaped control chars',
            input: { content: 'para — ' + 'x'.repeat(50000) + '\nsecond line\ttab', key: 'k' },
        },
    ])('round-trips valid JSON with $name', async ({ input }) => {
        const { tool, captured } = makeCaptureTool()
        const exec = createExecTool([tool], mockContext, 'd', 'r', undefined)
        await exec.handler(mockContext, { command: `call --json capture-tool ${JSON.stringify(input)}` })
        expect(captured()).toEqual(input)
    })

    // The old generic "Invalid JSON input" misdirected callers into blaming their own
    // escaping. The message must now report the received length and, for a body that
    // ends mid-value, name truncation-in-transit as the likely cause instead.
    it.each([
        { name: 'unterminated string', body: '{"content":"unclosed', hint: 'truncated in transit' },
        { name: 'other syntax error', body: '{"a": , }', hint: 'before assuming an escaping problem' },
    ])('formatInvalidJsonInput reports length and steers diagnosis for $name', ({ body, hint }) => {
        let msg = ''
        try {
            JSON.parse(body)
        } catch (err) {
            msg = formatInvalidJsonInput(body, err)
        }
        expect(msg).toContain(`received ${body.length} chars`)
        expect(msg).toContain(hint)
    })
})
