import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { regionAnchorAt } from './artifactComments'
import { taskArtifactCommentsLogic } from './taskArtifactCommentsLogic'

const TASK_ID = 'task-123'
const ARTIFACT_ID = 'artifact-chart'

const ROOT = {
    id: 'root-1',
    created_by: null,
    created_at: '2026-09-30T18:00:00Z',
    content: 'Is this axis right?',
    scope: 'task_artifact',
    item_id: ARTIFACT_ID,
    source_comment: null,
    completed_at: null,
    item_context: { anchor: { kind: 'region', x: 0.4, y: 0.2, width: 0.035, height: 0.035 }, taskId: TASK_ID },
}

describe('taskArtifactCommentsLogic', () => {
    const originalFetch = global.fetch
    let posted: Record<string, unknown>[]

    beforeEach(() => {
        initKeaTests()
        posted = []
        global.fetch = jest.fn((_input: RequestInfo | URL, init?: RequestInit) => {
            if (init?.method === 'POST') {
                posted.push(JSON.parse(String(init.body)))
                return Promise.resolve(
                    new Response(JSON.stringify({ ...ROOT, id: `saved-${posted.length}` }), {
                        headers: { 'Content-Type': 'application/json' },
                    })
                )
            }
            return Promise.resolve(
                new Response(JSON.stringify({ results: [ROOT], next: null }), {
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        }) as typeof fetch
    })

    afterEach(() => {
        global.fetch = originalFetch
    })

    // Desktop lists artifact comments by task id from the context and draws pins from the anchor, so a write
    // without either would not show there.
    it('writes pins and resolves in the shape Desktop reads', async () => {
        const logic = taskArtifactCommentsLogic({ taskId: TASK_ID, artifactId: ARTIFACT_ID, kind: 'image' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPinMode(true)
        logic.actions.setPendingAnchor(regionAnchorAt(0.5, 0.5), null)
        logic.actions.setDraft('pending', '  The legend covers the bars  ')
        logic.actions.submitComment('pending')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setThreadResolved(ROOT.id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(posted).toEqual([
            expect.objectContaining({
                scope: 'task_artifact',
                item_id: ARTIFACT_ID,
                content: 'The legend covers the bars',
                item_context: { anchor: regionAnchorAt(0.5, 0.5), taskId: TASK_ID },
            }),
            expect.objectContaining({
                scope: 'task_artifact',
                item_id: ARTIFACT_ID,
                source_comment: ROOT.id,
                item_context: { ...ROOT.item_context, threadState: 'resolved' },
            }),
        ])
        await expectLogic(logic).toMatchValues({
            pinMode: false,
            pendingAnchor: null,
            activeThreadId: 'saved-1',
            writing: null,
        })
    })
})
