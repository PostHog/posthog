import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowsFirstRunTab } from './WorkflowsFirstRunTab'

describe('WorkflowsFirstRunTab', () => {
    afterEach(() => {
        cleanup()
        clearAllCachedHasData()
    })

    it.each([
        { project: 'without workflows', workflowCount: 0, shows: 'workflows-first-run-gallery', enabled: true },
        { project: 'with a workflow', workflowCount: 1, shows: 'workflows-table', enabled: true },
        {
            project: 'without workflows when first run is off',
            workflowCount: 0,
            shows: 'workflows-table',
            enabled: false,
        },
    ])('shows a project $project the $shows', async ({ workflowCount, shows, enabled }) => {
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

        const { container } = render(<WorkflowsFirstRunTab />)

        await waitFor(() => expect(container.querySelector(`[data-attr="${shows}"]`)).toBeInTheDocument())
        expect(
            container.querySelectorAll('[data-attr="workflows-first-run-gallery"], [data-attr="workflows-table"]')
        ).toHaveLength(1)
    })
})
