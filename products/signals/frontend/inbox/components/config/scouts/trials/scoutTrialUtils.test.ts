import { trialFixtureComparison, trialFixtureResult, trialFixtureSetup } from './scoutTrialsFixtures'
import { comparisonScoreDisabledReason, initialTrialVariants, trialFormError } from './scoutTrialUtils'

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

    test.each([
        ['unknown', null, 'confirmed result'],
        ['not_started', null, 'not started'],
        ['unexpected_status', null, 'finish'],
        ['failed', 'running', 'finish'],
        ['running', 'running', 'finish'],
    ])('does not score a comparison while a run has status=%s and task status=%s', (status, taskStatus, reason) => {
        const results = Object.fromEntries(
            trialFixtureComparison.groups.flatMap((group) =>
                group.launchIds.map((launchId) => [
                    launchId,
                    { ...trialFixtureResult, launch_id: launchId, status, task_status: taskStatus },
                ])
            )
        )
        expect(comparisonScoreDisabledReason(trialFixtureComparison, results)).toContain(reason)
        expect(comparisonScoreDisabledReason(trialFixtureComparison, {})).toContain('confirmed result')
    })
})
