import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    notebooksWidgetCancel,
    notebooksWidgetGenerate,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
} from 'products/notebooks/frontend/generated/api'
import type { WidgetStatusApi, WidgetVersionPageApi } from 'products/notebooks/frontend/generated/api.schemas'

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

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksWidgetCancel).mockReset()
        jest.mocked(notebooksWidgetGenerate).mockReset()
        jest.mocked(notebooksWidgetStatus).mockReset()
        jest.mocked(notebooksWidgetVersions).mockReset().mockResolvedValue(emptyVersions)
        props.persistNotebook.mockClear()
    })

    afterEach(() => {
        logic?.unmount()
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

    it('formats elapsed generation time', () => {
        expect(formatWidgetElapsed(65)).toBe('01:05')
    })
})
