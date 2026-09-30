import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrialComparisonHistory,
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
    trialFixtureSetup,
} from './scoutTrialsFixtures'
import { ScoutTrialsPanel } from './ScoutTrialsPanel'

jest.mock('products/signals/frontend/generated/api', () => ({
    ...jest.requireActual('products/signals/frontend/generated/api'),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigTrialComparisonHistory: jest.fn(),
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
                expect(screen.getByRole('button', { name: 'New trial' }).getAttribute('aria-disabled')).toBe('false')
            )
            await userEvent.click(screen.getByRole('button', { name: 'New trial' }))
            expect((await screen.findByRole('button', { name: 'Start trial' })).getAttribute('aria-disabled')).toBe(
                'true'
            )

            await act(async () =>
                resolveRubric({
                    ...savedRubric,
                    reference_context: hasReference ? scoutRubricReferenceFixture : null,
                    reference_generation_id: hasReference ? 'example-generation' : null,
                })
            )

            await waitFor(() =>
                expect(screen.getByRole('button', { name: 'Start trial' }).getAttribute('aria-disabled')).toBe(
                    hasReference ? 'false' : 'true'
                )
            )
            expect(await screen.findByText('Graded with the saved rubric')).not.toBeNull()
            expect(signalsScoutRubricsRetrieve).toHaveBeenCalledWith('2', trialFixtureConfig.id)
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
