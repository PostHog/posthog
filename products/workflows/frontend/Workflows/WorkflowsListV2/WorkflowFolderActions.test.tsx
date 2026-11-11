import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowFolderActions } from './WorkflowFolderActions'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'

describe('WorkflowFolderActions', () => {
    let releaseOtherFiles: () => void

    beforeEach(() => {
        const otherFilesHeld = new Promise<void>((resolve) => (releaseOtherFiles = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                '/api/projects/:team_id/hog_flows/metrics/global/': () => [200, []],
                '/api/projects/:team_id/file_system/unfiled/': () => [200, { count: 0 }],
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search') ?? ''
                    if (search.startsWith('-')) {
                        await otherFilesHeld
                        return [200, paginated([{ id: 'dashboards', path: 'Reports', type: 'folder' }])]
                    }
                    return [
                        200,
                        paginated(search === 'type:folder' ? [{ id: 'billing', path: 'Billing', type: 'folder' }] : []),
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        workflowFoldersLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const submitButton = (): HTMLElement => screen.getByText('Submit').closest('button') as HTMLElement

    const clickRename = async (): Promise<void> => {
        render(<WorkflowFolderActions path="Billing" count={0} />)
        fireEvent.click(screen.getByLabelText('Actions for folder Billing'))
        fireEvent.click(await screen.findByText('Rename…'))
    }

    it("opens a rename once other products' files load, and checks names against them", async () => {
        await waitFor(() => expect(workflowFoldersLogic.values.browserReady).toBe(true))
        await clickRename()
        expect(screen.queryByText('Rename Billing')).toBeNull()
        cleanup()

        releaseOtherFiles()
        await waitFor(() => expect(workflowFoldersLogic.values.takenFolderPaths).not.toBeNull())
        await clickRename()
        const input = await screen.findByDisplayValue('Billing')
        fireEvent.change(input, { target: { value: 'reports' } })
        await waitFor(() => expect(submitButton()).toHaveAttribute('aria-disabled', 'true'))
        fireEvent.change(input, { target: { value: 'Invoices' } })
        await waitFor(() => expect(submitButton()).not.toHaveAttribute('aria-disabled', 'true'))
    })
})
