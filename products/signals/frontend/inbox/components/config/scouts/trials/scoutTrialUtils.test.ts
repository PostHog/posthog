import { initialTrialVariants, trialFormError } from './scoutTrialUtils'
import { trialFixtureSetup } from './scoutTrialsFixtures'

describe('scout comparison validation', () => {
    test.each([0, 1.5, 11, 100])('rejects %s repeats when the comparison has two variants', (repeats) => {
        expect(trialFormError(trialFixtureSetup, initialTrialVariants(trialFixtureSetup), repeats)).not.toBeNull()
    })

    it('rejects efforts unsupported by a model and blank prompt replacements before spending on a run', () => {
        const variants = initialTrialVariants(trialFixtureSetup)
        expect(trialFormError(trialFixtureSetup, [{ ...variants[0], effort: 'unsupported' }], 1)).toContain(
            'supported model and effort'
        )
        expect(trialFormError(trialFixtureSetup, [{ ...variants[0], replacePrompt: true, prompt: ' ' }], 1)).toContain(
            'replacement prompt'
        )
        expect(
            trialFormError(
                { ...trialFixtureSetup, ready: false, blocked_reason: 'Gateway capture is disabled.' },
                variants,
                1
            )
        ).toBe('Gateway capture is disabled.')
        expect(trialFormError(trialFixtureSetup, variants, 10)).toBeNull()
    })
})
