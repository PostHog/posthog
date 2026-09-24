import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlowCodeApi } from 'products/workflows/frontend/generated/api.schemas'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

const WORKFLOW_ID = 'wf-copy-code-1'
const CODE = "export const wf = workflow({ key: 'wf' })"

const SAVED_WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Copy code test',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
}

describe('workflowLogic copy code', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let codeBodies: Record<string, any>[]
    let codeResponse: () => [number, HogFlowCodeApi | { detail: string }]
    const copyToClipboardMock = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>
    const originalClipboard = navigator.clipboard
    const originalClipboardItem = globalThis.ClipboardItem

    const useClipboardWrite = (write: jest.Mock): void => {
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write } })
        Object.defineProperty(globalThis, 'ClipboardItem', {
            configurable: true,
            value: jest.fn((items) => ({ items })),
        })
    }

    beforeEach(async () => {
        codeBodies = []
        codeResponse = () => [200, { language: 'typescript', code: CODE, warnings: [] }]
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: originalClipboard })
        Object.defineProperty(globalThis, 'ClipboardItem', { configurable: true, value: originalClipboardItem })
        copyToClipboardMock.mockReset().mockResolvedValue(true)
        jest.spyOn(lemonToast, 'info').mockImplementation(() => 'toast-id')
        jest.spyOn(lemonToast, 'warning').mockImplementation(() => 'toast-id')
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': SAVED_WORKFLOW,
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/code/': async ({ request }) => {
                    codeBodies.push((await request.json()) as Record<string, any>)
                    return codeResponse()
                },
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await logic.asyncActions.loadWorkflow()
    })

    afterEach(() => {
        logic?.unmount()
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: originalClipboard })
        Object.defineProperty(globalThis, 'ClipboardItem', { configurable: true, value: originalClipboardItem })
        jest.restoreAllMocks()
    })

    it('copies the rendered source with the default toast when nothing was lost', async () => {
        await logic.asyncActions.copyWorkflowCode()

        expect(copyToClipboardMock).toHaveBeenCalledWith(CODE, 'workflow code', { silent: false })
        expect(lemonToast.warning).not.toHaveBeenCalled()
        expect(logic.values.copyCodePending).toBe(false)
    })

    it.each([
        [
            1,
            'Copied the workflow code. 1 part of this workflow cannot be expressed in code. It is listed at the top of the file.',
        ],
        [
            2,
            'Copied the workflow code. 2 parts of this workflow cannot be expressed in code. They are listed at the top of the file.',
        ],
    ])('replaces the default toast with one that counts %i lost part(s)', async (count, message) => {
        codeResponse = () => [
            200,
            {
                language: 'typescript',
                code: CODE,
                warnings: Array.from({ length: count }, (_, i) => ({ action_id: `step_${i}`, message: 'lost' })),
            },
        ]

        await logic.asyncActions.copyWorkflowCode()

        expect(copyToClipboardMock).toHaveBeenCalledWith(CODE, 'workflow code', { silent: true })
        expect(lemonToast.warning).toHaveBeenCalledWith(message)
    })

    it('starts a ClipboardItem write before the code request resolves', async () => {
        const write = jest.fn().mockResolvedValue(undefined)
        useClipboardWrite(write)

        await logic.asyncActions.copyWorkflowCode()

        expect(write).toHaveBeenCalledTimes(1)
        expect(globalThis.ClipboardItem).toHaveBeenCalledWith({ 'text/plain': expect.any(Promise) })
        expect(copyToClipboardMock).not.toHaveBeenCalled()
        expect(lemonToast.info).toHaveBeenCalledWith('Copied workflow code to clipboard')
        expect(lemonToast.warning).not.toHaveBeenCalled()
        expect(logic.values.copyCodePending).toBe(false)
    })

    it('shows the retry message when the ClipboardItem write fails', async () => {
        const write = jest.fn().mockRejectedValue(new Error('blocked'))
        useClipboardWrite(write)

        await logic.asyncActions.copyWorkflowCode()

        expect(write).toHaveBeenCalledTimes(1)
        expect(copyToClipboardMock).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Could not copy the workflow code. Please try again.')
        expect(logic.values.copyCodePending).toBe(false)
    })

    it('copies nothing and points to a retry when the endpoint fails', async () => {
        codeResponse = () => [500, { detail: 'boom' }]

        await logic.asyncActions.copyWorkflowCode()

        expect(copyToClipboardMock).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalledWith('Could not copy the workflow code. Please try again.')
        expect(logic.values.copyCodePending).toBe(false)
    })

    it('sends one request when the button is clicked twice while the first copy is in flight', async () => {
        logic.actions.copyWorkflowCode()
        expect(logic.values.copyCodePending).toBe(true)
        logic.actions.copyWorkflowCode()
        await expectLogic(logic).toFinishAllListeners()

        expect(codeBodies).toHaveLength(1)
        expect(copyToClipboardMock).toHaveBeenCalledTimes(1)
        expect(logic.values.copyCodePending).toBe(false)
    })

    it('copies the unsaved changes the editor holds', async () => {
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'Still typing')
        logic.actions.setWorkflowValue('edges', [])
        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.copyCodeDisabledReason).toBeUndefined()

        await logic.asyncActions.copyWorkflowCode()

        expect(codeBodies).toEqual([
            expect.objectContaining({ name: 'Still typing', edges: [], actions: SAVED_WORKFLOW.actions }),
        ])
        expect(copyToClipboardMock).toHaveBeenCalledWith(CODE, 'workflow code', { silent: false })
    })

    it('refuses to copy a new workflow before it is saved', async () => {
        logic.unmount()
        logic = workflowLogic({ id: 'new' })
        logic.mount()
        expect(logic.values.copyCodeDisabledReason).toBe('Save the workflow first')

        await logic.asyncActions.copyWorkflowCode()

        expect(codeBodies).toHaveLength(0)
        expect(copyToClipboardMock).not.toHaveBeenCalled()
    })
})
