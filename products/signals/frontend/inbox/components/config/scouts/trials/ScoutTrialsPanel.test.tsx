import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrialComparisonHistory,
    signalsScoutConfigTrialComparisonRetrieve,
    signalsScoutConfigTrialHistory,
    signalsScoutConfigTrialResult,
    signalsScoutConfigTrialSetup,
    signalsScoutRubricsRetrieve,
} from 'products/signals/frontend/generated/api'
import type { ScoutRubricDocumentApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import {
    trialFixtureConfig,
    trialFixtureEvaluation,
    trialFixtureResult,
    trialFixtureServerComparison,
    trialFixtureSetup,
} from './scoutTrialsFixtures'
import { ScoutTrialsPanel } from './ScoutTrialsPanel'

jest.mock('products/signals/frontend/generated/api', () => ({
    ...jest.requireActual('products/signals/frontend/generated/api'),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigTrialComparisonHistory: jest.fn(),
    signalsScoutConfigTrialComparisonRetrieve: jest.fn(),
    signalsScoutConfigTrialHistory: jest.fn(),
    signalsScoutConfigTrialResult: jest.fn(),
    signalsScoutConfigTrialSetup: jest.fn(),
    signalsScoutRubricsRetrieve: jest.fn(),
}))

const savedRubric: ScoutRubricDocumentApi = {
    config_id: trialFixtureConfig.id,
    skill_name: trialFixtureConfig.skill_name,
    revision: 2,
    criteria: trialFixtureEvaluation.report!.criteria.map((criterion) => ({
        ...criterion,
        enabled: true,
        source: 'custom',
    })),
    generation: null,
    reference_context: scoutRubricReferenceFixture,
    reference_generation_id: 'example-generation',
}

describe('ScoutTrialsPanel', () => {
    afterEach(cleanup)

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests(false)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], { [FEATURE_FLAGS.SCOUT_TRIALS]: true })
        jest.mocked(signalsScoutConfigList).mockResolvedValue([trialFixtureConfig])
        jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue(trialFixtureSetup)
        jest.mocked(signalsScoutConfigTrialHistory).mockResolvedValue({ results: [], has_more: false })
        jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({ results: [], has_more: false })
        jest.mocked(signalsScoutRubricsRetrieve).mockResolvedValue(savedRubric)
    })

    test.each([true, false])(
        'waits for a saved rubric before starting a trial with captured reference=%s',
        async (hasReference) => {
            let resolveRubric!: (value: ScoutRubricDocumentApi) => void
            jest.mocked(signalsScoutRubricsRetrieve).mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveRubric = resolve
                    })
            )
            render(<ScoutTrialsPanel teamId={2} userId={42} configId={trialFixtureConfig.id} />)

            expect(screen.queryByText('Start trial')).toBeNull()
            await waitFor(() =>
                expect(screen.getByTestId('scout-comparison-new').getAttribute('aria-disabled')).toBe('false')
            )
            await userEvent.click(screen.getByTestId('scout-comparison-new'))
            expect((await screen.findByTestId('scout-comparison-start')).getAttribute('aria-disabled')).toBe('true')

            await act(async () =>
                resolveRubric({
                    ...savedRubric,
                    reference_context: hasReference ? scoutRubricReferenceFixture : null,
                    reference_generation_id: hasReference ? 'example-generation' : null,
                })
            )

            await waitFor(() =>
                expect(screen.getByTestId('scout-comparison-start').getAttribute('aria-disabled')).toBe(
                    hasReference ? 'false' : 'true'
                )
            )
            expect(await screen.findByText('Graded with the saved rubric')).not.toBeNull()
            expect(signalsScoutRubricsRetrieve).toHaveBeenCalledWith('2', trialFixtureConfig.id)

            act(() => featureFlagLogic.actions.setFeatureFlags([], {}))
            expect(screen.getByTestId('scout-comparison-start').getAttribute('aria-disabled')).toBe('true')
            expect(screen.getByTestId('scout-trial-back').getAttribute('aria-disabled')).toBe('false')
            act(() =>
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], {
                    [FEATURE_FLAGS.SCOUT_TRIALS]: true,
                })
            )
            expect(screen.getByTestId('scout-comparison-start').getAttribute('aria-disabled')).toBe(
                hasReference ? 'false' : 'true'
            )
        }
    )

    test.each([undefined, trialFixtureConfig.id])(
        'keeps saved reports readable with trials disabled for config=%s',
        async (configId) => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
                results: [trialFixtureServerComparison],
                has_more: false,
            })
            jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue(trialFixtureServerComparison)
            jest.mocked(signalsScoutConfigTrialResult).mockResolvedValue(trialFixtureResult)

            render(<ScoutTrialsPanel teamId={2} userId={42} configId={configId} />)

            await userEvent.click(
                await screen.findByText(`Trial ${trialFixtureServerComparison.comparison_id.slice(0, 8)}`)
            )
            expect(await screen.findByText('Leaderboard')).not.toBeNull()
            expect(screen.getByTestId('scout-comparison-new').getAttribute('aria-disabled')).toBe('true')
            await userEvent.click(screen.getByText('Judge these runs again'))
            expect(
                screen.getByText('Prepare another judging attempt').closest('button')?.getAttribute('aria-disabled')
            ).toBe('true')
            expect(screen.getByText('Download report').closest('button')?.getAttribute('aria-disabled')).toBe('false')
        }
    )

    it('keeps the stop action available when a failed scout still has a task waiting to start', async () => {
        jest.mocked(signalsScoutConfigTrialHistory).mockResolvedValue({
            results: [
                {
                    ...trialFixtureResult,
                    variant: 'Baseline',
                    status: 'failed',
                    started_at: trialFixtureResult.started_at!,
                    run_id: trialFixtureResult.run_id!,
                    task_id: trialFixtureResult.task_id!,
                    task_run_id: trialFixtureResult.task_run_id!,
                },
            ],
            has_more: false,
        })
        jest.mocked(signalsScoutConfigTrialResult).mockResolvedValue({
            ...trialFixtureResult,
            status: 'failed',
            task_status: 'not_started',
        })

        render(<ScoutTrialsPanel teamId={2} userId={42} />)

        await userEvent.click(await screen.findByText('Individual run history'))
        expect(await screen.findByText('Stop run')).not.toBeNull()
    })
})
