import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'

import {
    notebooksWidgetCancel,
    notebooksWidgetGenerate,
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
    getWidgetDataDependencyNodeIds,
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

        expect(notebooksWidgetStatus).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe')
        expect(notebooksWidgetGenerate).not.toHaveBeenCalled()
    })

    it('loads version history when the widget has generated versions', async () => {
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

        expect(notebooksWidgetVersions).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            offset: 0,
            limit: 25,
        })
        expect(logic.values.versions).toEqual([version])
        expect(logic.values.versionsCount).toBe(1)
        expect(logic.values.versionsLoading).toBe(false)
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
        await expectLogic(logic).toDispatchActions(['statusReceived', 'loadVersions'])

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
        logic.actions.selectVersion(historicalVersion.id)

        logic.actions.refreshData()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenLastCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            offset: 0,
            limit: 25,
        })
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
            })
        )
        expect(logic.values.status?.active_job?.status).toBe('queued')
        expect(logic.values.generationRequestLoading).toBe(false)
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

        expect(getWidgetDataDependencyNodeIds(content, ['locations_df'])).toEqual(['source', 'transform'])
    })

    it('loads the selected version source and queues an improvement from it', async () => {
        const versionId = '00000000-0000-0000-0000-000000000009'
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({ lifecycle_status: 'ready', current_version_id: versionId, has_versions: true })
        )
        jest.mocked(notebooksWidgetSource).mockResolvedValue({ source: 'export default function Widget() {}' })
        jest.mocked(notebooksWidgetGenerate).mockResolvedValue(status({ lifecycle_status: 'generating' }))
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSourceModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetSource).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            version_id: versionId,
        })
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
            })
        )
        expect(logic.values.sourceModalOpen).toBe(false)
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

        expect(notebooksWidgetCancel).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            generation_id: active.active_job?.id,
        })
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
