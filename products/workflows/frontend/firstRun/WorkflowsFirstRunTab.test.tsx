import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowsFirstRunTab } from './WorkflowsFirstRunTab'

describe('WorkflowsFirstRunTab', () => {
    afterEach(() => {
        cleanup()
        clearAllCachedHasData()
    })

    it.each([
        { project: 'without workflows', workflowCount: 0, shows: 'workflows-first-run-gallery' },
        { project: 'with a workflow', workflowCount: 1, shows: 'workflows-table' },
    ])('shows a project $project the $shows', async ({ workflowCount, shows }) => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/': {
                    count: workflowCount,
                    results: [],
                },
            },
        })
        initKeaTests()

        const { container } = render(<WorkflowsFirstRunTab />)

        await waitFor(() => expect(container.querySelector(`[data-attr="${shows}"]`)).toBeInTheDocument())
        expect(
            container.querySelectorAll('[data-attr="workflows-first-run-gallery"], [data-attr="workflows-table"]')
        ).toHaveLength(1)
    })
})
