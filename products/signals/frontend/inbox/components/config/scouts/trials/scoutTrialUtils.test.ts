import { trialFixtureComparison, trialFixtureResult, trialFixtureSetup } from './scoutTrialsFixtures'
import { comparisonScoreDisabledReason, initialTrialVariants, trialFormError } from './scoutTrialUtils'

describe('scout trial validation', () => {
    test.each([0, 1.5, 21, 100])('rejects %s repeats when the trial has two versions', (repeats) => {
        expect(trialFormError(trialFixtureSetup, initialTrialVariants(trialFixtureSetup), repeats)).toBe(
            'Choose between 1 and 20 runs per version.'
        )
    })

    test.each([0, 1, 21])('rejects %s versions before starting a trial', (count) => {
        const baseline = initialTrialVariants(trialFixtureSetup)[0]
        const variants = Array.from({ length: count }, (_, index) => ({
            ...baseline,
            id: String(index),
            label: `Version ${index + 1}`,
        }))

        expect(trialFormError(trialFixtureSetup, variants, 1)).toBe('Use between 2 and 20 versions per trial.')
    })

    it('rejects efforts unsupported by a model and blank prompt replacements before spending on a run', () => {
        const variants = initialTrialVariants(trialFixtureSetup)
        expect(
            trialFormError(trialFixtureSetup, [{ ...variants[0], effort: 'unsupported' }, variants[1]], 1)
        ).toContain('supported model and effort')
        expect(
            trialFormError(trialFixtureSetup, [{ ...variants[0], replacePrompt: true, prompt: ' ' }, variants[1]], 1)
        ).toContain('replacement prompt')
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
        ['keeps the source model and effort', 'gpt-5.6-terra', 'high', 'gpt-5.6-terra', 'high'],
        ['leaves an unpinned effort blank', 'gpt-5.6-terra', null, 'gpt-5.6-terra', ''],
        ['leaves an unsupported effort blank', 'gpt-5.6-terra', 'max', 'gpt-5.6-terra', ''],
        ['leaves an unavailable source model blank', 'gpt-5.6-hidden', 'medium', '', ''],
    ])('%s for the baseline', (_name, sourceModel, sourceEffort, model, effort) => {
        const setup = { ...trialFixtureSetup, model: sourceModel, reasoning_effort: sourceEffort }
        const variants = initialTrialVariants(setup)

        expect(variants.map((variant) => [variant.model, variant.effort])).toEqual([
            [model, effort],
            [model, effort],
        ])
        expect(trialFormError(setup, variants, 1)).toBe(
            effort ? null : 'Choose a supported model and effort for every version.'
        )
    })

    test.each([
        ['unknown', null, 'confirmed result'],
        ['not_started', null, 'not started'],
        ['unexpected_status', null, 'finish'],
        ['failed', 'not_started', 'finish'],
        ['failed', 'queued', 'finish'],
        ['failed', 'in_progress', 'finish'],
        ['running', 'in_progress', 'finish'],
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
