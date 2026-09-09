import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    reusableWidgetsGenerate,
    reusableWidgetsRetrieve,
    reusableWidgetsStatus,
    reusableWidgetsVersions,
} from 'products/notebooks/frontend/generated/api'
import type { ReusableWidgetDetailApi, WidgetStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import { reusableWidgetLogic } from './reusableWidgetLogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    reusableWidgetsGenerate: jest.fn(),
    reusableWidgetsRetrieve: jest.fn(),
    reusableWidgetsStatus: jest.fn(),
    reusableWidgetsVersions: jest.fn(),
}))

const widget: ReusableWidgetDetailApi = {
    id: 'widget-1',
    name: 'Revenue',
    description: '',
    tags: [],
    publication_status: 'published',
    current_version: {
        id: 'version-1',
        title: 'Revenue',
        version: 1,
        operation: 'initial',
        model: null,
        artifact_url: 'https://example.com/widget.html',
        build_status: 'ready',
        build_hash: 'hash',
        frame_names: [],
        input_contract: [],
        security_review: null,
        has_demo_data: true,
        created_at: '2026-09-01T00:00:00Z',
    },
    pending_version: null,
    version_count: 1,
    instance_count: 1,
    created_at: '2026-09-01T00:00:00Z',
    published_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
}

const ready: WidgetStatusApi = {
    lifecycle_status: 'ready',
    error_detail: null,
    artifact_url: widget.current_version.artifact_url,
    frame_names: [],
    input_bindings: {},
    input_contract: [],
    current_version_id: 'version-1',
    pinned_version_id: null,
    widget_id: widget.id,
    instance_id: null,
    has_versions: true,
    active_job: null,
    security_review: null,
    is_reusable: true,
    build_hash: 'hash',
}

describe('reusableWidgetLogic', () => {
    let logic: ReturnType<typeof reusableWidgetLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.mocked(reusableWidgetsRetrieve).mockResolvedValue(widget)
        jest.mocked(reusableWidgetsVersions).mockResolvedValue({ results: [], count: 0, next_offset: null })
        jest.mocked(reusableWidgetsStatus).mockResolvedValue(ready)
        jest.mocked(reusableWidgetsGenerate).mockResolvedValue({ ...ready, lifecycle_status: 'generating' })
        logic = reusableWidgetLogic({ widgetId: widget.id })
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it.each(['failed', 'ready'] as const)(
        'preserves the prompt when generation ends with %s and no draft',
        async (lifecycle) => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.mocked(reusableWidgetsStatus).mockResolvedValue({
                ...ready,
                lifecycle_status: lifecycle,
                error_detail: lifecycle === 'failed' ? 'Source generation failed.' : null,
            })
            logic.actions.setChangePrompt('Group revenue by plan')
            await expectLogic(logic, () => logic.actions.updateReusableWidget()).toFinishAllListeners()
            expect(logic.values.updateInFlight).toBe(false)
            expect(logic.values.updateError).toBe(
                lifecycle === 'failed' ? 'Source generation failed.' : 'The reusable widget could not be updated.'
            )
            expect(logic.values.changePrompt).toBe('Group revenue by plan')
            expect(logic.values.reusableWidget?.current_version.id).toBe('version-1')
        }
    )

    it('resumes source generation on mount and discovers the finished draft', async () => {
        jest.mocked(reusableWidgetsStatus).mockResolvedValue({
            ...ready,
            lifecycle_status: 'generating',
            active_job: {
                id: 'job-1',
                status: 'generating',
                phase: 'generating_source',
                model: 'claude-sonnet-4-6',
                created_at: '2026-09-01T00:00:00Z',
                started_at: null,
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.updateInFlight).toBe(true)
        expect(logic.values.reusableWidget?.pending_version).toBeNull()
        const draft = { ...widget.current_version, id: 'version-2', version: 2 }
        jest.mocked(reusableWidgetsStatus).mockResolvedValue(ready)
        jest.mocked(reusableWidgetsRetrieve).mockResolvedValue({ ...widget, pending_version: draft })
        await expectLogic(logic, () => logic.actions.pollUpdate()).toFinishAllListeners()
        expect(logic.values.selectedVersion?.id).toBe('version-2')
        expect(logic.values.updateInFlight).toBe(false)
        expect(logic.values.updateError).toBeNull()
    })
})
