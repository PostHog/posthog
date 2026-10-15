import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
    isIdleResumeTurnComplete,
    isPiTurnError,
    isSessionUpdate,
    isTurnComplete,
    turnCompletedSuccessfully,
} from '../../src/lib/side-effects.js'

const cases = JSON.parse(
    readFileSync(new URL('../../../../ee/hogai/sandbox/turn_event_contract.json', import.meta.url), 'utf8')
) as {
    name: string
    event: Record<string, unknown>
    expect: Record<string, boolean>
}[]

// The fixture also carries expectations for predicates only one side has, so
// each side compares the keys it implements.
describe('turn event contract', () => {
    it.each(cases)('$name', ({ event, expect: expected }) => {
        const actual = {
            turn_complete: isTurnComplete(event),
            idle_resume: isIdleResumeTurnComplete(event),
            pi_error: isPiTurnError(event),
            session_update: isSessionUpdate(event),
            successful: turnCompletedSuccessfully(event),
        }
        expect(actual).toEqual(Object.fromEntries(Object.keys(actual).map((key) => [key, expected[key]])))
    })
})
