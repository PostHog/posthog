import { HogFlowActionValidationResult } from '../types'
import { validationBadgeReasons } from './validationBadge'

const base: HogFlowActionValidationResult = { valid: true, schema: null, errors: {}, warnings: {} }

describe('validationBadgeReasons', () => {
    it('returns nothing for a valid step', () => {
        expect(validationBadgeReasons(base)).toEqual([])
    })

    it('stays quiet for an invalid step whose field messages are still held back', () => {
        // An email step is invalid the moment it's added, but its per-field messages wait for a
        // save attempt. The badge must not appear with no reason to show.
        expect(validationBadgeReasons({ ...base, valid: false })).toEqual([])
    })

    it('carries the field messages once they are revealed', () => {
        const result: HogFlowActionValidationResult = {
            ...base,
            valid: false,
            emailErrors: { from: 'Choose an email sender, or connect a new one' },
        }
        expect(validationBadgeReasons(result)).toEqual(['Choose an email sender, or connect a new one'])
    })
})
