import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import type { JSONContent } from 'lib/components/RichContentEditor/types'
import { notebookNodeSQLV2Logic } from 'scenes/notebooks/Nodes/notebookNodeSQLV2Logic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'

import {
    notebooksWidgetCancel,
    notebooksWidgetGenerate,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
    notebooksSqlV2StateRetrieve,
} from 'products/notebooks/frontend/generated/api'
import type {
    WidgetStatusApi,
    WidgetVersionApi,
    WidgetVersionPageApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import { formatWidgetElapsed, notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksWidgetCancel: jest.fn(),
    notebooksWidgetFrame: jest.fn(),
    notebooksWidgetGenerate: jest.fn(),
    notebooksWidgetRevert: jest.fn(),
    notebooksWidgetSaveSource: jest.fn(),
    notebooksWidgetSource: jest.fn(),
    notebooksWidgetStatus: jest.fn(),
    notebooksWidgetVersions: jest.fn(),
    notebooksSqlV2StateRetrieve: jest.fn(),
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
        ...overrides,
    }
}

const emptyVersions: WidgetVersionPageApi = { results: [], count: 0, next_offset: null }

describe('notebookNodeGeneratedWidgetLogic', () => {
    const props = {
        notebookShortId: 'notebook-1',
        nodeId: 'globe',
        prompt: 'Render a globe',
        model: 'claude-sonnet-4-6' as const,
        isEditable: true,
        persistNotebook: jest.fn(async () => undefined),
    }
    let logic: ReturnType<typeof notebookNodeGeneratedWidgetLogic.build>
    let cellLogics: ReturnType<typeof notebookNodeSQLV2Logic.build>[]

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksWidgetCancel).mockReset()
        jest.mocked(notebooksWidgetGenerate).mockReset()
        jest.mocked(notebooksWidgetStatus).mockReset()
        jest.mocked(notebooksWidgetVersions).mockReset().mockResolvedValue(emptyVersions)
        jest.mocked(notebooksSqlV2StateRetrieve).mockReset()
        props.persistNotebook.mockClear()
        cellLogics = []
    })

    afterEach(() => {
        logic?.unmount()
        cellLogics.forEach((cellLogic) => cellLogic.unmount())
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
            operation: 'initial',
            prompt_delta: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget.html',
            frame_names: [],
            is_current: true,
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

    it('reloads versions after a reset arrives during an in-flight request', async () => {
        const initialVersion: WidgetVersionApi = {
            id: '00000000-0000-0000-0000-000000000002',
            parent_version_id: null,
            version: 1,
            operation: 'initial',
            prompt_delta: 'Render a globe',
            model: 'claude-sonnet-4-6',
            created_at: '2026-08-26T12:00:00Z',
            build_status: 'ready',
            artifact_url: 'https://example.com/widget-v1.html',
            frame_names: [],
            is_current: true,
        }
        const currentVersion: WidgetVersionApi = {
            ...initialVersion,
            id: '00000000-0000-0000-0000-000000000003',
            version: 2,
            artifact_url: 'https://example.com/widget-v2.html',
        }
        let resolveInitialRequest: (page: WidgetVersionPageApi) => void = () => undefined
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                artifact_url: initialVersion.artifact_url,
                current_version_id: initialVersion.id,
                has_versions: true,
            })
        )
        jest.mocked(notebooksWidgetVersions)
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveInitialRequest = resolve
                    })
            )
            .mockResolvedValueOnce({ results: [currentVersion], count: 1, next_offset: null })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['statusReceived', 'loadVersions'])

        logic.actions.loadVersions(true)
        resolveInitialRequest({ results: [initialVersion], count: 1, next_offset: null })
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetVersions).toHaveBeenCalledTimes(2)
        expect(logic.values.versions).toEqual([currentVersion])
    })

    it('refreshes the signed preview URL before reloading the frame', async () => {
        jest.mocked(notebooksWidgetStatus)
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-old.html' })
            )
            .mockResolvedValueOnce(
                status({ lifecycle_status: 'ready', artifact_url: 'https://example.com/widget-new.html' })
            )
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.refreshData()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.status?.artifact_url).toBe('https://example.com/widget-new.html')
        expect(logic.values.frameRevision).toBe(1)
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

    it('submits generation once and follows the durable queued job', async () => {
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

        logic.actions.generateWidget('Render a globe', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksWidgetGenerate).toHaveBeenCalledTimes(1)
        expect(notebooksWidgetGenerate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            expect.objectContaining({
                prompt: 'Render a globe',
                generation_id: expect.any(String),
                model: 'claude-sonnet-4-6',
                operation: 'initial',
            })
        )
        expect(logic.values.status?.active_job?.status).toBe('queued')
        expect(logic.values.generationRequestLoading).toBe(false)
        expect(logic.values.isWorking).toBe(true)
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

    it('runs stale prerequisites and the current frame producer before reloading the widget', async () => {
        const versionId = '00000000-0000-0000-0000-000000000002'
        const content: JSONContent = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.SQLV2,
                    attrs: { nodeId: 'source', returnVariable: 'source_df', code: 'select 1' },
                },
                {
                    type: NotebookNodeType.PythonV2,
                    attrs: {
                        nodeId: 'transform',
                        returnVariable: 'transformed_df',
                        code: 'transformed_df = source_df.head()',
                    },
                },
                {
                    type: NotebookNodeType.PythonV2,
                    attrs: {
                        nodeId: 'event-types',
                        returnVariable: 'event_types_df',
                        code: 'event_types_df = transformed_df.head()',
                    },
                },
            ],
        }
        jest.mocked(notebooksWidgetStatus).mockResolvedValue(
            status({
                lifecycle_status: 'ready',
                artifact_url: 'https://example.com/widget.html',
                frame_names: ['event_types_df'],
                current_version_id: versionId,
                has_versions: true,
            })
        )
        jest.mocked(notebooksSqlV2StateRetrieve).mockResolvedValue({
            notebook_id: 'notebook-1',
            title: 'Widget notebook',
            version: 1,
            markdown: '',
            kernel: { status: 'stopped' },
            cells: [
                {
                    node_id: 'source',
                    cell_type: 'sql',
                    dataframe_name: 'source_df',
                    code: 'select 1',
                    status: 'stale',
                    depends_on: [],
                    dependents: ['transform'],
                },
                {
                    node_id: 'transform',
                    cell_type: 'python',
                    dataframe_name: 'transformed_df',
                    code: 'transformed_df = source_df.head()',
                    status: 'done',
                    depends_on: ['source'],
                    dependents: ['event-types'],
                },
                {
                    node_id: 'event-types',
                    cell_type: 'python',
                    dataframe_name: 'event_types_df',
                    code: 'event_types_df = transformed_df.head()',
                    status: 'done',
                    depends_on: ['transform'],
                    dependents: [],
                },
            ],
        })
        for (const nodeId of ['source', 'transform', 'event-types']) {
            const cellLogic = notebookNodeSQLV2Logic({
                nodeId,
                notebookShortId: 'notebook-1',
                updateAttributes: jest.fn(),
                getContent: () => content,
            })
            cellLogic.mount()
            cellLogics.push(cellLogic)
        }
        const runSpy = jest.spyOn(api.notebooks, 'sqlV2Run').mockImplementation(async (_shortId, request) => ({
            run_id: `run-${request.node_id}`,
        }))
        jest.spyOn(api.notebooks, 'sqlV2RunResult').mockResolvedValue({
            status: 'done',
            result: { columns: [], first_page: [], row_count: 0 },
            error: null,
        })
        logic = notebookNodeGeneratedWidgetLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.runWidget()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(cellLogics[0]).toFinishAllListeners()
        await expectLogic(cellLogics[1]).toFinishAllListeners()
        await expectLogic(cellLogics[2]).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(props.persistNotebook).toHaveBeenCalledTimes(1)
        expect(notebooksSqlV2StateRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1')
        expect(runSpy.mock.calls.map((call) => call[1].node_id)).toEqual(['source', 'transform', 'event-types'])
        expect(logic.values.dataRunInFlight).toBe(false)
        expect(logic.values.frameRevision).toBe(1)
    })

    it('formats elapsed generation time', () => {
        expect(formatWidgetElapsed(65)).toBe('01:05')
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
