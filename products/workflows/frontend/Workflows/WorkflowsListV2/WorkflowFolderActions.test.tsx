import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowFolderActions } from './WorkflowFolderActions'
import { workflowFoldersLogic } from './workflowFoldersLogic'
import { FIXTURE_WORKFLOWS, paginated } from './workflowsListV2Fixtures'

type OpenFormConfig = Parameters<typeof LemonDialog.openForm>[0]

describe('WorkflowFolderActions', () => {
    let releaseOtherFiles: () => void
    let dialog: OpenFormConfig | undefined
    let openFormSpy: jest.SpyInstance<void, [OpenFormConfig]>

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
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_PROJECT_FILES]: true })
        workflowFoldersLogic.mount()
        dialog = undefined
        openFormSpy = jest.spyOn(LemonDialog, 'openForm').mockImplementation((config) => {
            dialog = config
        })
    })

    afterEach(() => {
        openFormSpy.mockRestore()
        cleanup()
    })

    it("checks a rename opened before other products' files load against them once they have", async () => {
        await waitFor(() => expect(workflowFoldersLogic.values.browserReady).toBe(true))
        render(<WorkflowFolderActions path="Billing" count={0} />)
        fireEvent.click(screen.getByLabelText('Actions for folder Billing'))
        fireEvent.click(await screen.findByText('Rename…'))
        const nameError = (name: string): string | undefined => dialog?.errors?.name(name, { name })
        expect(nameError('reports')).toBe('Checking existing folder names. Try again in a moment.')

        releaseOtherFiles()
        await waitFor(() => expect(workflowFoldersLogic.values.takenFolderPaths).not.toBeNull())
        expect(nameError('reports')).toBe('A folder with this name already exists')
    })
})
