import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import { uploadRunOutputVersion } from '../../utils/artifactUpload'
import type { RunArtifact } from './taskRunArtifacts'
import { artifactDownloadUrl, taskRunArtifactsLogic } from './taskRunArtifactsLogic'

jest.mock('../../utils/artifactUpload', () => ({ uploadRunOutputVersion: jest.fn() }))

const TASK_ID = 'task-123'
const RUN_ID = 'run-1'

function reportVersion(id: string, uploadedAt: string): TaskRunArtifactResponseApi {
    return {
        id,
        name: 'report.md',
        type: 'output',
        source: 'agent_output',
        content_type: 'text/markdown',
        storage_path: `tasks/artifacts/${id}`,
        uploaded_at: uploadedAt,
    }
}

describe('taskRunArtifactsLogic', () => {
    const originalFetch = global.fetch
    let runArtifacts: TaskRunArtifactResponseApi[] = []

    beforeEach(() => {
        initKeaTests()
        runArtifacts = []
        jest.mocked(uploadRunOutputVersion).mockReset()
        global.fetch = jest.fn((input: RequestInfo | URL) => {
            const url = String(input)
            if (url.includes('/artifacts/download/')) {
                return Promise.resolve(new Response('# Report'))
            }
            if (url.includes('/artifacts/') && url.includes('/preview/')) {
                return Promise.resolve(
                    new Response(
                        JSON.stringify({
                            url: 'https://usercontent.example/canvas-artifacts/task-preview/token/index.html',
                        }),
                        {
                            headers: { 'Content-Type': 'application/json' },
                        }
                    )
                )
            }
            const payload = /\/runs\/(\?.*)?$/.test(url)
                ? { results: runArtifacts.length ? [{ id: RUN_ID }] : [] }
                : url.includes('/living_artifacts/')
                  ? { artifacts: [] }
                  : url.includes(`/runs/${RUN_ID}/`)
                    ? { id: RUN_ID, artifacts: runArtifacts }
                    : { id: TASK_ID }
            return Promise.resolve(
                new Response(JSON.stringify(payload), { headers: { 'Content-Type': 'application/json' } })
            )
        }) as typeof fetch
    })

    afterEach(() => {
        global.fetch = originalFetch
    })

    it('opens a shared artifact link and keeps the url on the open file', async () => {
        router.actions.push(`/project/1/tasks/${TASK_ID}`, { artifact: 'report.md', artifact_version: 'v1' })
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            activeTab: 'artifacts',
            selectedFileKey: 'report.md',
            selectedVersionId: 'v1',
        })

        // The copied link must reopen the same file and version.
        expect(logic.values.shareUrl).toBe(
            `http://localhost/project/${logic.values.currentProjectId}/ai?task=${TASK_ID}&artifact=report.md&artifact_version=v1`
        )

        logic.actions.selectArtifact('chart.svg')
        expect(router.values.searchParams).toEqual({ artifact: 'chart.svg' })

        logic.actions.setActiveTab('conversation')
        expect(router.values.searchParams).toEqual({})
    })

    it('shows the list first on a phone and opens no file until one is picked', async () => {
        const originalWidth = window.innerWidth
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
        try {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            })
            runArtifacts = [reportVersion('report-v1', '2026-09-28T18:00:00Z')]
            router.actions.push('/project/1/ai', { task: TASK_ID })
            const capture = jest.spyOn(posthog, 'capture')
            const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
            logic.mount()
            logic.actions.setActiveTab('artifacts')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.showArtifactList).toBe(true)
            expect(router.values.searchParams).toEqual({ task: TASK_ID })
            expect(capture).not.toHaveBeenCalledWith('task artifact previewed', expect.anything())

            logic.actions.selectArtifact('report.md')
            expect(logic.values.showArtifactList).toBe(false)
            expect(router.values.searchParams).toEqual({ task: TASK_ID, artifact: 'report.md' })
            expect(capture).toHaveBeenCalledWith(
                'task artifact previewed',
                expect.objectContaining({ kind: 'markdown', source: 'click' })
            )

            logic.actions.setCommentsOpen(true)
            logic.actions.closeArtifact()
            expect(logic.values.showArtifactList).toBe(true)
            expect(router.values.searchParams).toEqual({ task: TASK_ID })

            logic.actions.selectArtifact('report.md')
            expect(logic.values.commentsOpen).toBe(false)
        } finally {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
        }
    })

    it('ignores an artifact link for another task', async () => {
        router.actions.push('/project/1/tasks/other-task', { artifact: 'report.md' })
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()

        await expectLogic(logic).toMatchValues({ activeTab: 'conversation', selectedFileKey: null })
    })

    it('loads each selected HTML preview once and ignores an old response', async () => {
        runArtifacts = ['interactive.html', 'second.html'].map((name, index) => ({
            id: `html-${index + 1}`,
            name,
            type: 'output',
            source: 'agent_output',
            content_type: 'text/html',
            storage_path: `tasks/artifacts/html-${index + 1}`,
            uploaded_at: '2026-09-28T18:00:00Z',
        }))
        const fetch = global.fetch
        const pending: Array<(response: Response) => void> = []
        global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
            String(input).includes('/preview/')
                ? new Promise<Response>((resolve) => pending.push(resolve))
                : fetch(input, init)
        )
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()
        await expectLogic(logic, () => logic.actions.setActiveTab('artifacts')).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.ensureSelectedText()).toMatchValues({ htmlPreviewLoading: true })
        logic.actions.ensureSelectedText()
        expect(pending).toHaveLength(1)
        expect(global.fetch).toHaveBeenCalledWith(
            expect.stringContaining(`/tasks/${TASK_ID}/runs/${RUN_ID}/artifacts/html-1/preview/`),
            expect.anything()
        )

        logic.actions.selectArtifact('second.html')
        logic.actions.ensureSelectedText()
        expect(pending).toHaveLength(2)
        await expectLogic(logic, () =>
            pending[1](
                new Response(
                    JSON.stringify({
                        url: 'https://usercontent.example/canvas-artifacts/task-preview/second/index.html',
                    }),
                    {
                        headers: { 'Content-Type': 'application/json' },
                    }
                )
            )
        )
            .toDispatchActions(['loadHtmlPreviewSuccess'])
            .toMatchValues({
                htmlPreviewLoading: false,
                htmlPreview: expect.objectContaining({ artifactId: 'html-2' }),
            })
        pending[0](
            new Response(
                JSON.stringify({ url: 'https://usercontent.example/canvas-artifacts/task-preview/first/index.html' }),
                {
                    headers: { 'Content-Type': 'application/json' },
                }
            )
        )
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.htmlPreview?.artifactId).toBe('html-2')
        expect(logic.values.htmlPreview?.url).toContain('/task-preview/second/')
    })

    it.each([
        [
            'a stored Slack file version streams from its version URL',
            true,
            `/api/projects/1/tasks/${TASK_ID}/runs/run-1/living_artifacts/doc-1/versions/3/`,
        ],
        ['a living version with no stored file has no URL', false, null],
    ])('artifactDownloadUrl: %s', (_, stored, expected) => {
        const version: RunArtifact = {
            id: 'living-doc-1-v3',
            name: 'signups.png',
            type: 'living',
            content_type: 'image/png',
            uploaded_at: '2026-09-30T16:00:00Z',
            runId: 'run-1',
            living: { artifactId: 'doc-1', version: 3, adapter: 'slack_file', text: null, stored },
        }
        expect(artifactDownloadUrl(1, TASK_ID, version)).toBe(expected)
    })

    it('asks before a save replaces a version the agent wrote during the edit', async () => {
        runArtifacts = [reportVersion('report-v1', '2026-09-28T18:00:00Z')]
        jest.mocked(uploadRunOutputVersion).mockResolvedValue('report-v3')
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()
        logic.actions.setActiveTab('artifacts')
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.ensureSelectedText()).toFinishAllListeners()
        expect(logic.values.selectedText?.text).toBe('# Report')

        logic.actions.startEditing()
        logic.actions.setEditDraft('# Report, edited')
        runArtifacts = [...runArtifacts, reportVersion('report-v2', '2026-09-28T18:10:00Z')]
        await expectLogic(logic, () => logic.actions.saveEdit()).toFinishAllListeners()

        expect(logic.values.editConflict).toBe('newer-version')
        expect(uploadRunOutputVersion).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.resolveEditConflict('save_as_latest')).toFinishAllListeners()

        expect(uploadRunOutputVersion).toHaveBeenCalledWith(expect.any(String), TASK_ID, RUN_ID, {
            name: 'report.md',
            content: '# Report, edited',
            contentType: 'text/markdown',
        })
        expect(logic.values).toMatchObject({ isEditing: false, editConflict: null })
    })
})
