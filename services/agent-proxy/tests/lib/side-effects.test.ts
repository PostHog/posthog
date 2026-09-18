import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { isIdleResumeTurnComplete, isPiTurnError, isSessionUpdate, isTurnComplete } from '../../src/lib/side-effects.js'

const cases = JSON.parse(
    readFileSync(new URL('../../../../ee/hogai/sandbox/turn_event_contract.json', import.meta.url), 'utf8')
) as {
    name: string
    event: Record<string, unknown>
    expect: { turn_complete: boolean; idle_resume: boolean; pi_error: boolean; session_update: boolean }
}[]

describe('turn event contract', () => {
    it.each(cases)('$name', ({ event, expect: expected }) => {
        expect({
            turn_complete: isTurnComplete(event),
            idle_resume: isIdleResumeTurnComplete(event),
            pi_error: isPiTurnError(event),
            session_update: isSessionUpdate(event),
        }).toEqual(expected)
    })
})
