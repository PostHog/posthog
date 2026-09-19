import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/replay'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// A session's first URL is whatever the user's browser was pointed at, so it can be an OAuth
// callback carrying a live token. Both replay tools return it, and a tool result reaches the
// calling agent's transcript.
const START_URL = 'https://app.example.com/callback?access_token=nx41ZmFrZXRva2VuMDAx&next=%2Fhome'
const REDACTED_START_URL = 'https://app.example.com/callback?access_token=[redacted]&next=%2Fhome'

const RECORDING = {
    id: '019fake-session-id',
    distinct_id: 'person-1',
    start_url: START_URL,
    recording_duration: 42,
    click_count: 7,
    person: { id: 11, name: 'Test person', properties: { email: 'someone@example.com' } },
}

function mockContext(response: unknown): Context {
    return {
        stateManager: { getProjectId: async () => 1 },
        api: {
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
            request: async () => response,
            query: () => ({ runQuery: async () => response }),
        },
    } as unknown as Context
}

function tool(name: string): ToolBase<ZodObjectAny> {
    return (GENERATED_TOOLS[name] as () => ToolBase<ZodObjectAny>)()
}

describe('session recording URL redaction', () => {
    it('redacts start_url on session-recording-get', async () => {
        const result: any = await tool('session-recording-get').handler(mockContext(RECORDING), {
            id: RECORDING.id,
        })

        expect(result.start_url).toBe(REDACTED_START_URL)
        expect(result.click_count).toBe(7)
    })

    it('redacts start_url on every row of query-session-recordings-list', async () => {
        const result: any = await tool('query-session-recordings-list').handler(
            mockContext({ results: [RECORDING, { ...RECORDING, id: 'second-session-id' }] }),
            { kind: 'RecordingsQuery' }
        )

        expect(result.results.map((row: any) => row.start_url)).toEqual([REDACTED_START_URL, REDACTED_START_URL])
        expect(result.results[0].recording_duration).toBe(42)
    })

    it('keeps the PostHog deep link intact, so its query and fragment still resolve', async () => {
        const result: any = await tool('query-session-recordings-list').handler(mockContext({ results: [RECORDING] }), {
            kind: 'RecordingsQuery',
        })

        expect(result._posthogUrl).toBe('https://us.posthog.com/project/1/replay')
    })
})
