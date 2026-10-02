import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { RunArtifact } from './taskRunArtifacts'
import { taskRunArtifactsLogic } from './taskRunArtifactsLogic'

const TASK_ID = 'task-123'

describe('taskRunArtifactsLogic', () => {
    const originalFetch = global.fetch

    beforeEach(() => {
        initKeaTests()
        global.fetch = jest.fn((input: RequestInfo | URL) => {
            const url = String(input)
            if (url.endsWith('/living_artifacts/doc-1/versions/3/')) {
                return Promise.resolve(new Response('week,signups\n1,40', { headers: { 'Content-Type': 'text/csv' } }))
            }
            const payload = url.endsWith('/runs/') ? { results: [] } : { id: TASK_ID }
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

    it('ignores an artifact link for another task', async () => {
        router.actions.push('/project/1/tasks/other-task', { artifact: 'report.md' })
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()

        await expectLogic(logic).toMatchValues({ activeTab: 'conversation', selectedFileKey: null })
    })

    it('reads a stored Slack file version through the version content endpoint', async () => {
        const logic = taskRunArtifactsLogic({ taskId: TASK_ID })
        logic.mount()
        const version: RunArtifact = {
            id: 'living-doc-1-v3',
            name: 'signups.csv',
            type: 'living',
            content_type: 'text/csv',
            uploaded_at: '2026-09-30T16:00:00Z',
            runId: 'run-1',
            living: { artifactId: 'doc-1', version: 3, adapter: 'slack_file', text: null, stored: true },
        }

        await expectLogic(logic, () => logic.actions.loadArtifactText(version))
            .toDispatchActions(['loadArtifactTextSuccess'])
            .toMatchValues({
                textsById: {
                    'living-doc-1-v3': { artifactId: 'living-doc-1-v3', text: 'week,signups\n1,40', error: null },
                },
            })
    })
})
