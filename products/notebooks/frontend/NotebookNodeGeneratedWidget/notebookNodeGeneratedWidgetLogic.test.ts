import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'

import {
    notebooksWidgetCancel,
    notebooksWidgetGenerate,
    notebooksWidgetRevert,
    notebooksWidgetSource,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
} from 'products/notebooks/frontend/generated/api'
import type {
    WidgetStatusApi,
    WidgetVersionApi,
    WidgetVersionPageApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import {
    formatWidgetElapsed,
    getWidgetDataDependencies,
    getWidgetWorkingStatus,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { DEFAULT_WIDGET_PROMPT } from './widgetModels'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksWidgetCancel: jest.fn(),
    notebooksWidgetFrame: jest.fn(),
    notebooksWidgetGenerate: jest.fn(),
    notebooksWidgetRevert: jest.fn(),
    notebooksWidgetSource: jest.fn(),
    notebooksWidgetStatus: jest.fn(),
    notebooksWidgetVersions: jest.fn(),
}))

function status(overrides: Partial<WidgetStatusApi> = {}): WidgetStatusApi {
    return {
        lifecycle_status: 'awaiting_generation',
        error_detail: null,
        artifact_url: null,
        frame_names: [],
        current_version_id: null,
        widget_id: null,
        instance_id: null,
        has_versions: false,
        active_job: null,
        security_review: null,
        build_hash: null,
        ...overrides,
    }
}

const emptyVersions: WidgetVersionPageApi = { results: [], count: 0, next_offset: null }

describe('notebookNodeGeneratedWidgetLogic', () => {
    const props = {
        projectId: MOCK_TEAM_ID,
        notebookShortId: 'notebook-1',
        nodeId: 'globe',
        prompt: 'Render a globe',
        model: 'claude-sonnet-4-6' as const,
        isEditable: true,
        persistNotebook: jest.fn(async () => undefined),
        getContent: jest.fn(() => null),
    }
    let logic: ReturnType<typeof notebookNodeGeneratedWidgetLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksWidgetCancel).mockReset()
        jest.mocked(notebooksWidgetGenerate).mockReset()
        jest.mocked(notebooksWidgetRevert).mockReset()
        jest.mocked(notebooksWidgetSource).mockReset()
        jest.mocked(notebooksWidgetStatus).mockReset()
        jest.mocked(notebooksWidgetVersions).mockReset().mockResolvedValue(emptyVersions)
        props.persistNotebook.mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('loads status without generating on mount', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetStatus).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(notebooksWidgetGenerate).not.toHaveBeenCalled()
    })

    it('times out a status request instead of leaving the widget loading forever', async () => {
        jest.useFakeTimers()
        jest.mocked(notebooksWidgetStatus).mockImplementation(
            (_projectId, _shortId, _nodeId, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(options.signal?.reason), { once: true })
                })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()

        await jest.advanceTimersByTimeAsync(30_000)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.statusLoadError).toBe('The widget request timed out.')
        expect(logic.values.statusLoading).toBe(false)
    })

    it('aborts outstanding widget requests when the node unmounts', async () => {
        let requestSignal: AbortSignal | undefined
        jest.mocked(notebooksWidgetStatus).mockImplementation(
            (_projectId, _shortId, _nodeId, options) =>
                new Promise((_resolve, reject) => {
                    requestSignal = options?.signal ?? undefined
                    requestSignal?.addEventListener('abort', () => reject(requestSignal?.reason), { once: true })
                })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()

        logic.unmount()
        await Promise.resolve()

        expect(requestSignal?.aborted).toBe(true)
    })

    it('ignores an aborted mutation request after the node unmounts', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetGenerate).mockImplementation(
            (_projectId, _shortId, _nodeId, _body, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(options?.signal?.reason), { once: true })
                })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const statusCallsBeforeUnmount = jest.mocked(notebooksWidgetStatus).mock.calls.length

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'regenerate')
        await expectLogic(logic).toDispatchActions(['generationRequestStarted'])

        logic.unmount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        // The unmount abort must not open a recovery status read on a logic that is going away.
        expect(jest.mocked(notebooksWidgetStatus).mock.calls.length).toBe(statusCallsBeforeUnmount)
    })

    it.each(['../other-widget', 'folder/widget', 'widget?status', 'widget#status'])(
        'rejects the unsafe widget identifier %s before making a request',
        async (nodeId) => {
            logic = notebookNodeGeneratedWidgetLogic({ ...props, nodeId })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(notebooksWidgetStatus).not.toHaveBeenCalled()
            expect(logic.values.statusLoadError).toBe('This widget has an invalid identifier.')
        }
    )

    it('loads version history when requested', async () => {
        const version: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget.html',
            frame_names: [],
            is_current: true,
            security_review: null,
            build_hash: 'a'.repeat(64),
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                artifact_url: version.artifact_url,
                current_version_id: version.id,
                has_versions: true,
            })
        )
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [version],
            count: 1,
            next_offset: null,
        })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(notebooksWidgetVersions).not.toHaveBeenCalled()

        logic.actions.loadVersions(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            { offset: 0, limit: 25 },
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(logic.values.versions).toEqual([version])
        expect(logic.values.versionsCount).toBe(1)
        expect(logic.values.versionsLoading).toBe(false)
    })

    it('loads version history when the first version appears mid-generation', async () => {
        const firstVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget.html',
            frame_names: [],
            is_current: true,
            security_review: null,
            build_hash: 'a'.repeat(64),
        }
        // The first status carries no version, matching a settings panel opened before generation.
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({ results: [firstVersion], count: 1, next_offset: null })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(notebooksWidgetVersions).not.toHaveBeenCalled()

        logic.actions.statusReceived(
            status({
                lifecycle_status: 'ready',
                artifact_url: firstVersion.artifact_url,
                current_version_id: firstVersion.id,
                has_versions: true,
            })
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenCalledTimes(1)
        expect(logic.values.versions).toEqual([firstVersion])
        expect(logic.values.selectedVersion?.id).toBe(firstVersion.id)
    })

    it('ignores repeated status polls and reloads explicit resets during an in-flight request', async () => {
        const initialVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget-v1.html',
            frame_names: [],
            is_current: true,
            security_review: null,
            build_hash: 'b'.repeat(64),
        }
        const currentVersion: WidgetVersionApi = {
            ...initialVersion,
            id: '00000000-0000-0000-0000-000000000003',
            version: 2,
            artifact_url: 'https://example.com/widget-v2.html',
        }
        let resolveInitialRequest: (page: WidgetVersionPageApi) => void = () => undefined
        let resolveResetRequest: (page: WidgetVersionPageApi) => void = () => undefined
        const readyStatus = status({
            lifecycle_status: 'ready',
            artifact_url: initialVersion.artifact_url,
            current_version_id: initialVersion.id,
            has_versions: true,
        })
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(readyStatus)
        jest.mocked(notebooksWidgetVersions)
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveInitialRequest = resolve
                    })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveResetRequest = resolve
                    })
            )
            .mockResolvedValueOnce({ results: [currentVersion], count: 1, next_offset: null })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['statusReceived'])

        expect(notebooksWidgetVersions).not.toHaveBeenCalled()
        logic.actions.loadVersions(true)

        logic.actions.statusReceived(readyStatus)
        resolveInitialRequest({ results: [initialVersion], count: 1, next_offset: null })
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenCalledTimes(1)
        expect(logic.values.versions).toEqual([initialVersion])

        logic.actions.loadVersions(true)
        logic.actions.loadVersions(true)
        resolveResetRequest({ results: [initialVersion], count: 1, next_offset: null })
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenCalledTimes(3)
        expect(logic.values.versions).toEqual([currentVersion])
    })

    it('refreshes the signed preview URL before reloading the frame', async () => {
        let resolveReload: (status: WidgetStatusApi) => void = () => undefined
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-old.html' })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveReload = resolve
                    })
            )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.refreshData()
        expect(logic.values.dataRefreshInFlight).toBe(true)
        resolveReload(status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-new.html' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.artifact_url).toBe('https://example.com/widget-new.html')
        expect(logic.values.frameRevision).toBe(1)
        expect(logic.values.dataRefreshInFlight).toBe(false)
    })

    it('reloads the preview when a newer status request supersedes the refresh', async () => {
        let resolveRefresh: (status: WidgetStatusApi) => void = () => undefined
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-old.html' })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveRefresh = resolve
                    })
            )
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-current.html' })
            )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.refreshData()
        logic.actions.loadStatus()
        resolveRefresh(status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-old.html' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.artifact_url).toBe('https://example.com/widget-current.html')
        expect(logic.values.frameRevision).toBe(1)
        expect(logic.values.dataRefreshInFlight).toBe(false)
    })

    it('reloads the preview when a status poll fails while widget data cells are running', async () => {
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-old.html' })
            )
            .mockRejectedValueOnce(new Error('Temporary status failure'))
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-new.html' })
            )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.dataRefreshStarted()
        logic.actions.loadStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dataRefreshInFlight).toBe(true)

        logic.actions.widgetDataChainFinished([])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.artifact_url).toBe('https://example.com/widget-new.html')
        expect(logic.values.frameRevision).toBe(1)
        expect(logic.values.dataRefreshInFlight).toBe(false)
    })

    it('keeps a widget-specific error when a connected data cell fails', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.dataRefreshStarted()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.abortChain('source-cell')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.dataRefreshInFlight).toBe(false)
        expect(logic.values.runtimeError).toContain('source-cell')
        expect(logic.values.runtimeError).toContain('run the widget data cells again')
    })

    it('refreshes a selected historical version before reloading the frame', async () => {
        const currentVersionId = '00000000-0000-0000-0000-000000000003'
        const historicalVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget-old.html',
            frame_names: [],
            is_current: false,
            security_review: null,
            build_hash: 'c'.repeat(64),
        }
        const readyStatus = status({
            lifecycle_status: 'ready',
            artifact_url: 'https://example.com/widget-current.html',
            current_version_id: currentVersionId,
            has_versions: true,
        })
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(readyStatus)
        jest.mocked(notebooksWidgetVersions)
            .mockResolvedValueOnce({ results: [historicalVersion], count: 1, next_offset: null })
            .mockResolvedValueOnce({
                results: [{ ...historicalVersion, artifact_url: 'https://example.com/widget-new.html' }],
                count: 1,
                next_offset: null,
            })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadVersions(true)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectVersion(historicalVersion.id)

        logic.actions.refreshData()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenLastCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            { offset: 0, limit: 25 },
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(logic.values.selectedVersion?.artifact_url).toBe('https://example.com/widget-new.html')
        expect(logic.values.frameRevision).toBe(1)
    })

    it('keeps the last ready version selected while a replacement builds', async () => {
        const previousVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget-v1.html',
            frame_names: [],
            is_current: true,
            security_review: null,
            build_hash: 'd'.repeat(64),
        }
        const nextVersionId = '00000000-0000-0000-0000-000000000003'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                artifact_url: previousVersion.artifact_url,
                current_version_id: previousVersion.id,
                has_versions: true,
            })
        )
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [previousVersion],
            count: 1,
            next_offset: null,
        })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadVersions(true)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.statusReceived(
            status({ lifecycle_status: 'building', current_version_id: nextVersionId, has_versions: true })
        )
        expect(logic.values.selectedVersionId).toBe(previousVersion.id)

        logic.actions.statusReceived(
            status({
                lifecycle_status: 'ready',
                artifact_url: 'https://example.com/widget-v2.html',
                current_version_id: nextVersionId,
                has_versions: true,
            })
        )
        expect(logic.values.selectedVersionId).toBe(nextVersionId)
    })

    it('refreshes version history when a replacement build fails', async () => {
        const previousVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            version_operation: 'initial',
            prompt_delta: 'Render a globe',
            effective_prompt: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget-v1.html',
            frame_names: [],
            is_current: true,
            security_review: null,
            build_hash: 'e'.repeat(64),
        }
        const failedVersion: WidgetVersionApi = {
            ...previousVersion,
            id: '00000000-0000-0000-0000-000000000003',
            parent_version_id: previousVersion.id,
            version: 2,
            version_operation: 'improve',
            prompt_delta: 'Add labels',
            effective_prompt: 'Render a globe\n\nAdd labels',
            build_status: 'failed',
            artifact_url: null,
            is_current: true,
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                artifact_url: previousVersion.artifact_url,
                current_version_id: previousVersion.id,
                has_versions: true,
            })
        )
        jest.mocked(notebooksWidgetVersions)
            .mockResolvedValueOnce({ results: [previousVersion], count: 1, next_offset: null })
            .mockResolvedValueOnce({
                results: [failedVersion, { ...previousVersion, is_current: false }],
                count: 2,
                next_offset: null,
            })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadVersions(true)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.statusReceived(
            status({
                lifecycle_status: 'failed',
                artifact_url: null,
                current_version_id: failedVersion.id,
                has_versions: true,
            })
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.versions[0].id).toBe(failedVersion.id)
        expect(logic.values.selectedVersionId).toBe(previousVersion.id)
    })

    it('keeps status errors separate from paid generation', async () => {
        jest.mocked(notebooksWidgetStatus).mockRejectedValue(new Error('offline'))
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.statusLoadError).toBe('offline')
        expect(logic.values.generationError).toBeNull()
        expect(notebooksWidgetGenerate).not.toHaveBeenCalled()
    })

    it.each([
        ['provided instructions', 'Render a globe', 'Render a globe'],
        ['an empty new-widget prompt', '', DEFAULT_WIDGET_PROMPT],
    ])('submits %s once and follows the durable queued job', async (_label, prompt, expectedPrompt) => {
        const queued = status({
            lifecycle_status: 'generating',
            active_job: {
                id: '00000000-0000-0000-0000-000000000001',
                status: 'queued',
                phase: 'queued',
                model: 'claude-sonnet-4-6',
                created_at: '2026-08-26T12:00:00Z',
                started_at: null,
            },
        })
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetGenerate).mockResolvedValue(queued)
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateWidget(prompt, 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetGenerate).toHaveBeenCalledTimes(1)
        expect(notebooksWidgetGenerate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            expect.objectContaining({
                prompt: expectedPrompt,
                generation_id: expect.any(String),
                model: 'claude-sonnet-4-6',
                generation_operation: 'initial',
            }),
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(logic.values.status?.active_job?.status).toBe('queued')
        expect(logic.values.generationRequestLoading).toBe(false)
        expect(logic.values.isWorking).toBe(true)
    })

    it('does not let an older status request overwrite a newly queued generation', async () => {
        const queued = status({
            lifecycle_status: 'generating',
            active_job: {
                id: '00000000-0000-0000-0000-000000000001',
                status: 'queued',
                phase: 'queued',
                model: 'claude-sonnet-4-6',
                created_at: '2026-08-26T12:00:00Z',
                started_at: null,
            },
        })
        let resolveOldStatus: (value: WidgetStatusApi) => void = () => undefined
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(status())
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveOldStatus = resolve
                    })
            )
        jest.mocked(notebooksWidgetGenerate).mockResolvedValue(queued)
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.loadStatus()
        await expectLogic(logic, () =>
            logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        ).toDispatchActions(['generationRequestStarted', 'statusReceived', 'generationRequestFinished'])

        expect(logic.values.status?.active_job?.status).toBe('queued')
        resolveOldStatus(status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/stale.html' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.active_job?.status).toBe('queued')
        expect(logic.values.isWorking).toBe(true)
    })

    it('finds the data producer and its transitive dependencies without unrelated cells', () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.SQLV2,
                    attrs: { nodeId: 'source', returnVariable: 'sql_df', code: 'select 1' },
                },
                {
                    type: NotebookNodeType.PythonV2,
                    attrs: {
                        nodeId: 'transform',
                        returnVariable: 'locations_df',
                        code: 'locations_df = sql_df.copy()',
                    },
                },
                {
                    type: NotebookNodeType.SQLV2,
                    attrs: { nodeId: 'unrelated', returnVariable: 'other_df', code: 'select 2' },
                },
            ],
        }

        expect(getWidgetDataDependencies(content, ['locations_df'])).toEqual({
            missingFrameNames: [],
            nodeIds: ['source', 'transform'],
        })
    })

    it('does not run a partial data chain when a widget frame has no matching cell', async () => {
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.SQLV2,
                    attrs: { nodeId: 'source', returnVariable: 'available_df', code: 'select 1' },
                },
            ],
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', frame_names: ['available_df', 'missing_df'], has_versions: true })
        )
        logic = notebookNodeGeneratedWidgetLogic({ ...props, getContent: () => content })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const toastError = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
        logic.actions.runDataDependencies()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.runtimeError).toContain('notebook data that is no longer available')
        // The banner is unmounted when the widget is collapsed, so the failure must also toast.
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining('notebook data that is no longer available'))
        expect(logic.values.dataRefreshInFlight).toBe(false)
    })

    it('loads the selected version source and queues an improvement from it', async () => {
        const versionId = '00000000-0000-0000-0000-000000000009'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', current_version_id: versionId, has_versions: true })
        )
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({
            results: [
                {
                    id: versionId,
                    parent_version_id: null,
                    version: 1,
                    version_operation: 'initial',
                    prompt_delta: 'Render a globe',
                    effective_prompt: 'Render a globe',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-26T12:00:00Z',
                    build_status: 'ready',
                    artifact_url: null,
                    frame_names: [],
                    is_current: true,
                    security_review: null,
                    build_hash: null,
                },
            ],
            count: 1,
            next_offset: null,
        })
        jest.mocked(notebooksWidgetSource).mockResolvedValue({ source: 'export default function Widget() {}' })
        jest.mocked(notebooksWidgetGenerate).mockResolvedValue(status({ lifecycle_status: 'generating' }))
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSourceModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetStatus).toHaveBeenCalledTimes(2)
        expect(notebooksWidgetSource).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            { version_id: versionId },
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(logic.values.source).toBe('export default function Widget() {}')
        expect(logic.values.sourceModalOpen).toBe(true)

        logic.actions.setSourceChangePrompt('Use a darker background')
        logic.actions.improveSource()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetGenerate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            expect.objectContaining({
                prompt: 'Use a darker background',
                generation_operation: 'improve',
                expected_current_version_id: versionId,
            }),
            expect.objectContaining({ signal: expect.anything() })
        )
        expect(logic.values.sourceModalOpen).toBe(false)
    })

    it('waits for immutable version metadata before improving source', async () => {
        const versionId = '00000000-0000-0000-0000-000000000009'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', current_version_id: versionId, has_versions: true })
        )
        jest.mocked(notebooksWidgetSource).mockResolvedValue({ source: 'export default function Widget() {}' })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSourceModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSourceChangePrompt('Use a darker background')
        logic.actions.improveSource()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sourceImprovementDisabledReason).toBe('Loading the widget version.')
        expect(notebooksWidgetGenerate).not.toHaveBeenCalled()
    })

    it('does not improve a historical version as though it were current', async () => {
        const currentVersionId = '00000000-0000-0000-0000-000000000009'
        const historicalVersionId = '00000000-0000-0000-0000-000000000008'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', current_version_id: currentVersionId, has_versions: true })
        )
        jest.mocked(notebooksWidgetVersions).mockResolvedValue({ results: [], count: 0, next_offset: null })
        jest.mocked(notebooksWidgetSource).mockResolvedValue({ source: 'export default function Widget() {}' })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectVersion(historicalVersionId)
        logic.actions.openSourceModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSourceChangePrompt('Use a darker background')
        logic.actions.improveSource()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sourceImprovementDisabledReason).toBe('Restore this version before building changes.')
        expect(notebooksWidgetGenerate).not.toHaveBeenCalled()
    })

    it('keeps source responses bound to the selected version', async () => {
        const firstVersionId = '00000000-0000-0000-0000-000000000008'
        const secondVersionId = '00000000-0000-0000-0000-000000000009'
        let resolveFirstSource: (value: { source: string }) => void = () => undefined
        let resolveSecondSource: (value: { source: string }) => void = () => undefined
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', current_version_id: firstVersionId })
        )
        jest.mocked(notebooksWidgetSource)
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveFirstSource = resolve
                    })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveSecondSource = resolve
                    })
            )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSourceModal()
        logic.actions.closeSourceModal()
        logic.actions.statusReceived(status({ lifecycle_status: 'ready', current_version_id: secondVersionId }))
        logic.actions.selectVersion(secondVersionId)
        logic.actions.openSourceModal()

        await expectLogic(logic, () => resolveSecondSource({ source: 'source for version two' })).toDispatchActions([
            'sourceReceived',
        ])
        expect(logic.values.source).toBe('source for version two')
        expect(logic.values.sourceVersionId).toBe(secondVersionId)

        resolveFirstSource({ source: 'source for version one' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.source).toBe('source for version two')
        expect(logic.values.sourceVersionId).toBe(secondVersionId)
    })

    it('persists an older Markdown widget and retries with the same generation identifier', async () => {
        const queued = status({
            lifecycle_status: 'generating',
            active_job: {
                id: '00000000-0000-0000-0000-000000000001',
                status: 'queued',
                phase: 'queued',
                model: 'claude-sonnet-4-6',
                created_at: '2026-08-26T12:00:00Z',
                started_at: null,
            },
        })
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetGenerate)
            .mockRejectedValueOnce(
                new ApiError('Not found', 404, undefined, {
                    code: 'node_not_found',
                    detail: 'This generated widget is no longer in the notebook.',
                })
            )
            .mockResolvedValueOnce(queued)
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(props.persistNotebook).toHaveBeenCalledTimes(1)
        expect(notebooksWidgetGenerate).toHaveBeenCalledTimes(2)
        expect(jest.mocked(notebooksWidgetGenerate).mock.calls[1][3].generation_id).toBe(
            jest.mocked(notebooksWidgetGenerate).mock.calls[0][3].generation_id
        )
        expect(logic.values.status?.active_job?.status).toBe('queued')
    })

    it('recovers a durable generation when its response is lost', async () => {
        jest.mocked(notebooksWidgetStatus).mockImplementation(async () => {
            const generationId = jest.mocked(notebooksWidgetGenerate).mock.calls[0]?.[3].generation_id
            return generationId
                ? status({
                      lifecycle_status: 'generating',
                      active_job: {
                          id: generationId,
                          status: 'queued',
                          phase: 'queued',
                          model: 'claude-sonnet-4-6',
                          created_at: '2026-08-26T12:00:00Z',
                          started_at: null,
                      },
                  })
                : status()
        })
        jest.mocked(notebooksWidgetGenerate).mockRejectedValue(new Error('Connection closed'))
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.active_job?.status).toBe('queued')
        expect(logic.values.generationError).toBeNull()
        expect(logic.values.isWorking).toBe(true)
    })

    it('does not mistake a concurrent version change for a recovered generation', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetGenerate).mockRejectedValue(
            new ApiError('Another generation won the race.', 409, undefined, {
                detail: 'Another generation won the race.',
            })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetStatus).toHaveBeenCalledTimes(1)
        expect(logic.values.generationError).toBe('Another generation won the race.')
        expect(logic.values.isWorking).toBe(false)
    })

    it('surfaces field-level generation errors', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        jest.mocked(notebooksWidgetGenerate).mockRejectedValue(
            new ApiError('Invalid request', 400, undefined, {
                prompt: ['Keep widget instructions to 20,000 characters or fewer.'],
            })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.generationError).toBe('Keep widget instructions to 20,000 characters or fewer.')
    })

    it('refreshes status without claiming a restore succeeded when its response is lost', async () => {
        const currentVersionId = '00000000-0000-0000-0000-000000000010'
        const historicalVersionId = '00000000-0000-0000-0000-000000000009'
        const restoredVersionId = '00000000-0000-0000-0000-000000000011'
        const initialStatus = status({
            lifecycle_status: 'ready',
            current_version_id: currentVersionId,
            has_versions: true,
        })
        const restoredStatus = status({
            lifecycle_status: 'ready',
            artifact_url: 'https://example.com/restored.html',
            current_version_id: restoredVersionId,
            has_versions: true,
        })
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(initialStatus)
            .mockResolvedValueOnce(restoredStatus)
            .mockResolvedValue(restoredStatus)
        jest.mocked(notebooksWidgetRevert).mockRejectedValue(new Error('Connection closed'))
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectVersion(historicalVersionId)
        logic.actions.restoreSelectedVersion()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.current_version_id).toBe(restoredVersionId)
        expect(logic.values.selectedVersionId).toBe(restoredVersionId)
        expect(logic.values.restoreInFlight).toBe(false)
        expect(logic.values.generationError).toBe('Connection closed')
    })

    it("does not mistake another editor's version for a recovered restore", async () => {
        const currentVersionId = '00000000-0000-0000-0000-000000000010'
        const historicalVersionId = '00000000-0000-0000-0000-000000000009'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                current_version_id: currentVersionId,
                has_versions: true,
            })
        )
        jest.mocked(notebooksWidgetRevert).mockRejectedValue(
            new ApiError('The current version changed.', 409, undefined, {
                detail: 'The current version changed.',
            })
        )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectVersion(historicalVersionId)
        logic.actions.restoreSelectedVersion()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetStatus).toHaveBeenCalledTimes(1)
        expect(logic.values.status?.current_version_id).toBe(currentVersionId)
        expect(logic.values.selectedVersionId).toBe(historicalVersionId)
        expect(logic.values.generationError).toBe('The current version changed.')
        expect(logic.values.restoreInFlight).toBe(false)

        logic.actions.statusReceived(
            status({ lifecycle_status: 'ready', current_version_id: currentVersionId, has_versions: true })
        )
        expect(logic.values.generationError).toBeNull()
    })

    it('cancels the shared durable job from its status identifier', async () => {
        const active = status({
            lifecycle_status: 'generating',
            active_job: {
                id: '00000000-0000-0000-0000-000000000001',
                status: 'generating',
                phase: 'generating',
                model: 'claude-sonnet-4-6',
                created_at: '2026-08-26T12:00:00Z',
                started_at: '2026-08-26T12:00:01Z',
            },
        })
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(active)
        jest.mocked(notebooksWidgetCancel).mockResolvedValue(undefined)
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.cancelGeneration()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetCancel).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            { generation_id: active.active_job?.id },
            expect.objectContaining({ signal: expect.anything() })
        )
    })

    it('does not cancel generation from a read-only widget', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'generating',
                active_job: {
                    id: '00000000-0000-0000-0000-000000000001',
                    status: 'generating',
                    phase: 'generating',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-26T12:00:00Z',
                    started_at: '2026-08-26T12:00:01Z',
                },
            })
        )
        logic = notebookNodeGeneratedWidgetLogic({ ...props, isEditable: false })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.cancelGeneration()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetCancel).not.toHaveBeenCalled()
    })

    it('formats elapsed generation time', () => {
        expect(formatWidgetElapsed(65)).toBe('01:05')
    })

    it('shows the security review phase after source generation', () => {
        expect(
            getWidgetWorkingStatus({
                elapsedSeconds: 30,
                hasVersions: false,
                model: 'claude-sonnet-4-6',
                phase: 'reviewing_source',
            })
        ).toEqual({
            detail: 'Checking the generated source for security issues.',
            isOverEstimate: false,
            label: 'Reviewing widget security…',
            timing: 'This usually takes less than a minute.',
        })
    })

    it('keeps the elapsed clock running when generation hands off to publishing', async () => {
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(status())
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-08-26T12:00:05Z'))

        logic.actions.statusReceived(
            status({
                lifecycle_status: 'generating',
                active_job: {
                    id: '00000000-0000-0000-0000-000000000001',
                    status: 'generating',
                    phase: 'generating_source',
                    model: 'claude-sonnet-4-6',
                    created_at: '2026-08-26T12:00:00Z',
                    started_at: '2026-08-26T12:00:00Z',
                },
            })
        )
        expect(logic.values.elapsedSeconds).toBe(5)

        logic.actions.statusReceived(status({ lifecycle_status: 'building', has_versions: true }))
        jest.advanceTimersByTime(1_000)

        expect(logic.values.elapsedSeconds).toBe(6)
        expect(logic.values.workingStatus?.label).toBe('Publishing widget…')
    })
})
