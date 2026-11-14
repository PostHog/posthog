import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { aiFirstHandoffLogic } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { maxMocks } from 'scenes/max/testUtils'
import { urls } from 'scenes/urls'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'

import { newWorkflowFolderParam } from './newWorkflowFolder'
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
    // The toast text is captured as an analytics event, so it names no folder.
    const MOVE_WARNING =
        "Your workflow was created, but it couldn't be moved into the folder you picked. It's in Unfiled / Workflows."
    const WITH_ID = {
        content: [{ type: 'text', text: 'Created' }],
        _meta: { 'com.posthog.mcp/app_data': { id: WORKFLOW_ID } },
    }
    // A large create comes back as a notice, so the workflow is found by name.
    const WITHOUT_ID = { content: 'Error: result exceeds maximum allowed tokens.', isError: false }
    let moves: { path: string; pageAtMove: string }[]
    let logic: ReturnType<typeof aiFirstHandoffLogic.build> | null
    let unmountTree: (() => void) | null

    const flush = async (): Promise<void> => {
        for (let i = 0; i < 5; i++) {
            await new Promise((resolve) => setTimeout(resolve, 0))
        }
    }

    // Passed to useMocks in each test: a helper that calls useMocks itself trips the rules-of-hooks lint.
    function handoffMocks({
        lookup = async () => 'Unfiled/Workflows/Welcome',
        move = async () => 200,
    }: {
        lookup?: () => Promise<string>
        move?: () => Promise<number>
    }): Parameters<typeof useMocks>[0] {
        return {
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/hog_flows/': {
                    results: [{ id: WORKFLOW_ID, name: NAME, created_at: '2026-09-15T00:00:00Z' }],
                    count: 1,
                },
                '/api/projects/:team_id/file_system/': async ({ request }) => {
                    if (!new URL(request.url).searchParams.has('ref')) {
                        return { results: [], count: 0 }
                    }
                    const path = await lookup()
                    return { results: [{ id: 'workflow-file', path, type: 'hog_flow', ref: WORKFLOW_ID }], count: 1 }
                },
            },
            post: {
                ...maxMocks.post,
                '/api/projects/:team_id/file_system/workflow-file/move/': async ({ request }) => {
                    const path = ((await request.json()) as { new_path: string }).new_path
                    moves.push({ path, pageAtMove: router.values.location.pathname })
                    const status = await move()
                    return status === 200
                        ? [200, { id: 'workflow-file', path, type: 'hog_flow', ref: WORKFLOW_ID }]
                        : [status, { detail: 'Could not move workflow' }]
                },
            },
        }
    }

    function startHandoff(): void {
        moves = []
        initKeaTests()
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
        // The folder handoff exists only behind this flag, and the tree shows workflow files only with it on.
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_LIST_V2]: true })
        unmountTree = projectTreeDataLogic.mount()
        projectTreeDataLogic.actions.loadFolderSuccess(
            'Unfiled/Workflows',
            [{ id: 'workflow-file', path: 'Unfiled/Workflows/Welcome', type: 'hog_flow', ref: WORKFLOW_ID }],
            false,
            1
        )
        router.actions.push(urls.workflowNew(), newWorkflowFolderParam('007'))
        logic = aiFirstHandoffLogic(workflowHandoffInFolder('007', 50))
        logic.mount()
        runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setActiveCreation({ streamKey: 'folder-create' })
    }

    const completeCreate = (output: Record<string, unknown>): void =>
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
                input: { command: `call workflows-create ${JSON.stringify({ name: NAME })}` },
                output,
                status: 'completed',
                contentBlocks: [],
            },
        })

    const openedWorkflow = (): boolean => router.values.location.pathname.includes(WORKFLOW_ID)
    const placedAt = (): string => projectTreeDataLogic.values.itemsByRef[`hog_flow::${WORKFLOW_ID}`].path

    afterEach(() => {
        logic?.unmount()
        unmountTree?.()
        logic = null
        unmountTree = null
        cleanup()
    })

    it.each([
        { name: 'files it, then opens it', status: 200, placed: '007/Welcome', warned: false },
        {
            name: 'warns and opens it unfiled when the move fails',
            status: 500,
            placed: 'Unfiled/Workflows/Welcome',
            warned: true,
        },
    ])('$name', async ({ status, placed, warned }) => {
        useMocks(handoffMocks({ move: async () => status }))
        startHandoff()

        await act(async () => {
            await expectLogic(logic!, () => completeCreate(WITH_ID)).toFinishAllListeners()
        })

        expect(openedWorkflow()).toBe(true)
        expect(moves).toEqual([{ path: '007/Welcome', pageAtMove: expect.stringContaining('/new/workflow') }])
        expect(placedAt()).toBe(placed)
        await waitFor(() => expect(screen.queryByText(MOVE_WARNING) !== null).toBe(warned))
    })

    it('opens the workflow when filing stalls past the deadline', async () => {
        let releaseMove = (): void => {}
        useMocks(handoffMocks({ move: () => new Promise((resolve) => (releaseMove = () => resolve(500))) }))
        startHandoff()

        await expectLogic(logic!, () => completeCreate(WITH_ID)).toFinishAllListeners()

        expect(openedWorkflow()).toBe(true)
        expect(placedAt()).toBe('Unfiled/Workflows/Welcome')
        releaseMove()
    })

    // Names are not unique, so a workflow found by name may be someone else's.
    it('opens a workflow found by name without moving it', async () => {
        useMocks(handoffMocks({}))
        startHandoff()

        await expectLogic(logic!, () => completeCreate(WITHOUT_ID)).toFinishAllListeners()

        expect(openedWorkflow()).toBe(true)
        await flush()
        expect(moves).toEqual([])
    })

    it('leaves a workflow where it was put after the deadline opened it', async () => {
        let answerLookup = (_path: string): void => {}
        useMocks(handoffMocks({ lookup: () => new Promise((resolve) => (answerLookup = resolve)) }))
        startHandoff()

        await expectLogic(logic!, () => completeCreate(WITH_ID)).toFinishAllListeners()
        expect(openedWorkflow()).toBe(true)

        answerLookup('Elsewhere/Welcome')
        await flush()
        expect(moves).toEqual([])
        expect(screen.queryByText(MOVE_WARNING)).toBeNull()
    })

    // Past the deadline someone may file the workflow, so a lookup that answers late must not move it.
    it('does not move a workflow when the lookup answers after the deadline', async () => {
        let answerLookup = (_path: string): void => {}
        useMocks(handoffMocks({ lookup: () => new Promise((resolve) => (answerLookup = resolve)) }))
        startHandoff()

        await expectLogic(logic!, () => completeCreate(WITH_ID)).toFinishAllListeners()
        expect(openedWorkflow()).toBe(true)

        answerLookup('Unfiled/Workflows/Welcome')
        await flush()
        expect(moves).toEqual([])
        await waitFor(() => expect(screen.queryByText(MOVE_WARNING)).not.toBeNull())
    })
})
