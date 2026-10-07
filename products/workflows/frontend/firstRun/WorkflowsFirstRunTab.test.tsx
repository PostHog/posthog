import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { navPanelProductPushWelcomeLogic } from 'lib/components/NavPanelAdvertisement/navPanelProductPushWelcomeLogic'
import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { WorkflowsFirstRunTab } from './WorkflowsFirstRunTab'

const WELCOME = {
    campaignId: 'campaign-1',
    productKey: ProductKey.WORKFLOWS,
    label: 'Workflows',
    text: 'Message users when it matters.',
}

describe('WorkflowsFirstRunTab', () => {
    afterEach(() => {
        cleanup()
        clearAllCachedHasData()
    })

    it.each([
        {
            project: 'without workflows',
            workflowCount: 0,
            shows: 'workflows-first-run-gallery',
            enabled: true,
            holdsWelcome: true,
        },
        { project: 'with a workflow', workflowCount: 1, shows: 'workflows-table', enabled: true, holdsWelcome: false },
        {
            project: 'without workflows when first run is off',
            workflowCount: 0,
            shows: 'workflows-table',
            enabled: false,
            holdsWelcome: false,
        },
    ])('shows a project $project the $shows', async ({ workflowCount, shows, enabled, holdsWelcome }) => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/': {
                    count: workflowCount,
                    results: [],
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })
        const welcomeLogic = navPanelProductPushWelcomeLogic()
        welcomeLogic.mount()
        welcomeLogic.actions.setPendingWelcome(WELCOME)

        const { container, unmount } = render(<WorkflowsFirstRunTab />)

        welcomeLogic.actions.openWelcome(WELCOME)
        expect(welcomeLogic.values.openFor).toEqual(enabled ? null : WELCOME)

        await waitFor(() => expect(container.querySelector(`[data-attr="${shows}"]`)).toBeInTheDocument())
        expect(
            container.querySelectorAll('[data-attr="workflows-first-run-gallery"], [data-attr="workflows-table"]')
        ).toHaveLength(1)
        welcomeLogic.actions.openWelcome(WELCOME)
        expect(welcomeLogic.values.openFor).toEqual(holdsWelcome ? null : WELCOME)

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: false })
        welcomeLogic.actions.openWelcome(WELCOME)
        expect(welcomeLogic.values.openFor).toEqual(WELCOME)

        unmount()
        welcomeLogic.actions.openWelcome(WELCOME)
        expect(welcomeLogic.values.openFor).toEqual(WELCOME)
        welcomeLogic.unmount()
    })
})
