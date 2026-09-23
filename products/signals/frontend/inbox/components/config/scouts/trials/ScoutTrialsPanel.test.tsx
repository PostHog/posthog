import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrialHistory,
    signalsScoutConfigTrialSetup,
} from 'products/signals/frontend/generated/api'

import { trialFixtureConfig, trialFixtureSetup } from './scoutTrialsFixtures'
import { ScoutTrialsPanel } from './ScoutTrialsPanel'

jest.mock('products/signals/frontend/generated/api', () => ({
    ...jest.requireActual('products/signals/frontend/generated/api'),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigTrialHistory: jest.fn(),
    signalsScoutConfigTrialSetup: jest.fn(),
}))

describe('ScoutTrialsPanel', () => {
    it('renders loaded comparison settings through the logic binding', async () => {
        localStorage.clear()
        initKeaTests(false)
        jest.mocked(signalsScoutConfigList).mockResolvedValue([trialFixtureConfig])
        jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue(trialFixtureSetup)
        jest.mocked(signalsScoutConfigTrialHistory).mockResolvedValue({ results: [], has_more: false })

        render(<ScoutTrialsPanel teamId={2} userId={42} />)

        expect(await screen.findByText('Start 2 runs')).not.toBeNull()
        expect(screen.getByText('Checkout quality')).not.toBeNull()
    })
})
