import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/replay'

// A session recording is identified by its `$session_id`, and every neighbouring
// surface names that value `session_id`. Agents carry the name over to
// `session-recording-get`, whose canonical param is `id` — production traces show
// the mismatched key as the dominant validation failure for the tool. Every alias
// must normalize to `id` or those failures come back.
describe('session recording id aliases', () => {
    const ALIAS_KEYS = [
        'session_id',
        'recording_id',
        'session_recording_id',
        'sessionId',
        'recordingId',
        'sessionRecordingId',
    ] as const

    const schema = GENERATED_TOOLS['session-recording-get']!().schema
    const SESSION_ID = '019f0000-0000-7000-8000-000000000001'

    it.each([
        ['id', { id: SESSION_ID }],
        ['session_id', { session_id: SESSION_ID }],
        ['recording_id', { recording_id: SESSION_ID }],
        ['session_recording_id', { session_recording_id: SESSION_ID }],
        ['sessionId', { sessionId: SESSION_ID }],
        ['recordingId', { recordingId: SESSION_ID }],
        ['sessionRecordingId', { sessionRecordingId: SESSION_ID }],
        ['id over aliases on conflict', { id: SESSION_ID, session_id: 'other' }],
        ['first-listed alias on alias conflict', { session_id: SESSION_ID, recordingId: 'other' }],
    ])('accepts %s', (_label, input) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toBe(SESSION_ID)
        for (const alias of ALIAS_KEYS) {
            expect(data).not.toHaveProperty(alias)
        }
    })

    it('still rejects a call with no identifier', () => {
        expect(schema.safeParse({}).success).toBe(false)
    })
})
