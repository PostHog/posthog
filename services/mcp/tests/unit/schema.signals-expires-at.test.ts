import { describe, expect, it } from 'vitest'

import { SignalsScoutNotesCreateBody, SignalsScoutScratchpadRememberBody } from '@/generated/signals/api'

// Regression guard: the pipeline agents compute `expires_at` from a clock they can only guess at,
// so a share of writes carry a datetime with no UTC offset. The server reads that shape fine, but
// only if it arrives. A `format: date-time` on the field makes codegen emit
// `zod.iso.datetime({ offset: true })`, which refuses the value here and loses the whole write.
describe('Signals expires_at boundary tolerance', () => {
    it.each([
        ['scout-scratchpad-remember', SignalsScoutScratchpadRememberBody],
        ['scout-notes-create', SignalsScoutNotesCreateBody],
    ] as const)('accepts an expiry that names no offset through %s', (_label, body) => {
        const result = body().safeParse({
            key: 'pattern:impl:example',
            content: 'a memory worth keeping',
            expires_at: '2035-10-05T00:00:00',
        })

        expect(result.success).toBe(true)
    })
})
