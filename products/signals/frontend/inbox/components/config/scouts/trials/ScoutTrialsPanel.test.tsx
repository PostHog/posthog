import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrialComparisonHistory,
    signalsScoutConfigTrialHistory,
    signalsScoutConfigTrialResult,
    signalsScoutConfigTrialSetup,
} from 'products/signals/frontend/generated/api'

import { trialFixtureConfig, trialFixtureResult, trialFixtureSetup } from './scoutTrialsFixtures'
import { ScoutTrialsPanel } from './ScoutTrialsPanel'

jest.mock('products/signals/frontend/generated/api', () => ({
    ...jest.requireActual('products/signals/frontend/generated/api'),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigTrialComparisonHistory: jest.fn(),
    signalsScoutConfigTrialHistory: jest.fn(),
    signalsScoutConfigTrialResult: jest.fn(),
    signalsScoutConfigTrialSetup: jest.fn(),
}))

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
    })

    it('renders loaded comparison settings through the logic binding', async () => {
        render(<ScoutTrialsPanel teamId={2} userId={42} />)

        expect(await screen.findByText('Start comparison')).not.toBeNull()
        expect(screen.getByText('Checkout quality')).not.toBeNull()
    })

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
