import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { aiFirstHandoffLogic } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { maxMocks } from 'scenes/max/testUtils'
import { urls } from 'scenes/urls'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'

import { findCreatedWorkflowId, workflowHandoffInFolder } from './newWorkflowHandoff'

const WORKFLOW_ID = '2f1e9c3a-5b7d-4e8f-9a0b-1c2d3e4f5a6b'
const OLDER_ID = '7a1b2c3d-0000-4e8f-9a0b-1c2d3e4f5a6b'
const NAME = 'Win back inactive users'

describe('findCreatedWorkflowId', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // Ordered by update time like the real list, so the same-named older draft comes first.
                '/api/environments/:team_id/hog_flows/': {
                    results: [
                        { id: OLDER_ID, name: NAME, created_at: '2026-09-01T00:00:00Z' },
                        { id: WORKFLOW_ID, name: NAME, created_at: '2026-09-15T00:00:00Z' },
                        { id: 'other', name: `${NAME} v2`, created_at: '2026-09-16T00:00:00Z' },
                    ],
                    count: 3,
                },
            },
        })
        initKeaTests()
    })

    // The list is a substring search, so only the exact name counts, and the newest of those is the draft just made.
    it.each([
        { name: 'the newest exact match', input: NAME, expected: WORKFLOW_ID },
        { name: 'null for a blank name', input: '  ', expected: null },
        { name: 'null for a non-string name', input: 42, expected: null },
    ])('returns $name', async ({ input, expected }) => {
        await expect(findCreatedWorkflowId(input)).resolves.toBe(expected)
    })
})

describe('AI workflow folder handoff', () => {
    it.each([200, 500])('waits for folder persistence, then opens the created workflow (%s)', async (status) => {
        let movedPath = ''
        const toast = jest.spyOn(lemonToast, 'warning')
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/projects/:team_id/file_system/': ({ request }) => ({
                    results: new URL(request.url).searchParams.has('ref')
                        ? [
                              {
                                  id: 'workflow-file',
                                  path: 'Unfiled/Workflows/Welcome',
                                  type: 'hog_flow',
                                  ref: WORKFLOW_ID,
                              },
                          ]
                        : [],
                    count: new URL(request.url).searchParams.has('ref') ? 1 : 0,
                }),
            },
            post: {
                ...maxMocks.post,
                '/api/projects/:team_id/file_system/workflow-file/move/': async ({ request }) => {
                    expect(router.values.location.pathname).toContain('/new/workflow')
                    if (status !== 200) {
                        return [status, { detail: 'Could not move workflow' }]
                    }
                    movedPath = ((await request.json()) as { new_path: string }).new_path
                    return [200, { id: 'workflow-file', path: movedPath, type: 'hog_flow', ref: WORKFLOW_ID }]
                },
            },
        })
        initKeaTests()
        const unmountTree = projectTreeDataLogic.mount()
        projectTreeDataLogic.actions.loadFolderSuccess(
            'Unfiled/Workflows',
            [{ id: 'workflow-file', path: 'Unfiled/Workflows/Welcome', type: 'hog_flow', ref: WORKFLOW_ID }],
            false,
            1
        )
        router.actions.push(urls.workflowNew(), { _create_in_folder: '007' })
        const logic = aiFirstHandoffLogic(workflowHandoffInFolder('007'))
        logic.mount()
        runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setActiveCreation({ streamKey: 'folder-create' })
        try {
            await expectLogic(logic, () =>
                toolStreamEventsLogic.actions.emitToolEvent({
                    streamKey: 'folder-create',
                    toolCallId: 'call-folder',
                    toolName: 'workflows-create',
                    rawToolName: 'exec',
                    phase: 'completed',
                    source: 'live',
                    invocation: {
                        toolCallId: 'call-folder',
                        rawServerName: 'posthog',
                        rawToolName: 'exec',
                        input: { command: 'call workflows-create {}' },
                        output: {
                            content: [{ type: 'text', text: 'Created' }],
                            _meta: { 'com.posthog.mcp/app_data': { id: WORKFLOW_ID } },
                        },
                        status: 'completed',
                        contentBlocks: [],
                    },
                })
            ).toFinishAllListeners()
            if (status === 200) {
                expect(movedPath).toBe('007/Welcome')
                expect(projectTreeDataLogic.values.itemsByRef[`hog_flow::${WORKFLOW_ID}`].path).toBe('007/Welcome')
                expect(router.values.location.pathname).toContain(WORKFLOW_ID)
            } else {
                expect(movedPath).toBe('')
                expect(router.values.location.pathname).toContain(WORKFLOW_ID)
                expect(toast).toHaveBeenCalledWith(expect.stringContaining("couldn't be moved into 007"))
            }
        } finally {
            logic.unmount()
            unmountTree()
            toast.mockRestore()
        }
    })
})
