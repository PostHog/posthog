import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { initKeaTests } from '~/test/init'
import type { IntegrationType } from '~/types'

import {
    signalsFeaturesDiscoverCreate,
    signalsFeaturesDiscoveryRunsList,
    signalsFeaturesList,
} from 'products/signals/frontend/generated/api'

import { featureDiscoveryLogic } from './featureDiscoveryLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsFeaturesDiscoverCreate: jest.fn(),
    signalsFeaturesDiscoveryRunsList: jest.fn(),
    signalsFeaturesList: jest.fn(),
}))

const mockDiscover = jest.mocked(signalsFeaturesDiscoverCreate)
const mockListRuns = jest.mocked(signalsFeaturesDiscoveryRunsList)
const mockListFeatures = jest.mocked(signalsFeaturesList)

const GITHUB_INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'github',
    display_name: 'PostHog',
    icon_url: '/static/services/github.png',
    config: { account: { name: 'PostHog', type: 'Organization' }, repository_selection: 'all' },
    created_at: '2026-08-19T00:00:00Z',
}

describe('featureDiscoveryLogic', () => {
    let logic: ReturnType<typeof featureDiscoveryLogic.build>
    let unmountIntegrations: () => void

    beforeEach(() => {
        initKeaTests()
        mockDiscover.mockReset()
        mockDiscover.mockResolvedValue({ run_id: '019c0000-0000-7000-8000-000000000001' })
        mockListRuns.mockReset()
        mockListRuns.mockResolvedValue([])
        mockListFeatures.mockReset()
        mockListFeatures.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })

        unmountIntegrations = integrationsLogic.mount()
        integrationsLogic.actions.loadIntegrationsSuccess([GITHUB_INTEGRATION])
        logic = featureDiscoveryLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        unmountIntegrations()
    })

    it('qualifies the repository selected by the GitHub picker before starting discovery', async () => {
        logic.actions.setRepository('posthog')
        logic.actions.setFocus('Only discover features around session replay')

        await expectLogic(logic, () => logic.actions.startDiscovery()).toFinishAllListeners()

        expect(mockDiscover).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            repository: 'PostHog/posthog',
            focus: 'Only discover features around session replay',
        })
    })

    it('retries a failed discovery with its saved repository and focus', async () => {
        await expectLogic(logic, () =>
            logic.actions.retryDiscovery({
                repository: 'PostHog/posthog',
                focus: 'Only discover features around session replay',
            })
        ).toFinishAllListeners()

        expect(mockDiscover).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            repository: 'PostHog/posthog',
            focus: 'Only discover features around session replay',
        })
    })
})
