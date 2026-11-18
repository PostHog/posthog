import {
    historyFrames,
    initialSessionThread,
    type SessionThreadState,
    sessionThreadReducer,
} from '@/features/chat/session/sessionReducer'
import { decisionQuestionFor } from '@/features/handoff/permissionRequest'
import { initialRunState, reduceFrame } from '@/features/handoff/runStream'
import type { RunStreamState } from '@/features/handoff/types'

import { buildDemoChatList } from './chats'
import { buildDemoFixtures } from './fixtures'
import { type DemoSessionLog, demoSessionLog, demoSessionRunId } from './sessionThreads'

const ANCHOR = new Date(2026, 9, 7, 15, 0)
const SESSIONS = [
    ...buildDemoChatList(ANCHOR),
    ...buildDemoFixtures(ANCHOR).list.flatMap(({ report }) =>
        report.task
            ? [
                  {
                      sourceId: report.task.taskId,
                      title: report.title,
                      pullRequestUrl: report.work.pullRequests?.[0]?.url ?? report.work.pullRequest?.url ?? null,
                  },
              ]
            : []
    ),
]

function fold(taskId: string): { log: DemoSessionLog; thread: SessionThreadState; live: RunStreamState } {
    const log = demoSessionLog(taskId)
    if (!log) {
        throw new Error(`No demo log for ${taskId}`)
    }
    const runId = demoSessionRunId(taskId)
    const frames = historyFrames(log.entries, runId, false)
    const thread = sessionThreadReducer(initialSessionThread(), { type: 'frames', frames })
    let live = initialRunState(taskId, runId, log.status)
    for (const { frame, context } of frames) {
        live = reduceFrame(live, frame, context).state
    }
    return { log, thread, live }
}

describe('demo session logs', () => {
    test.each(SESSIONS.map((item) => [item.sourceId, item.title, item.pullRequestUrl]))(
        'the demo chats list row %s opens a stored session with the same title and PR',
        (sourceId, title, pullRequestUrl) => {
            const { log, thread, live } = fold(sourceId)
            expect(log.title).toBe(title)
            expect(thread.items[0]?.kind).toBe('user')
            expect(thread.items.some((item) => item.kind === 'tool')).toBe(true)
            expect(live.prUrl ?? null).toBe(pullRequestUrl)
        }
    )

    test('the in-progress session waits on a two-option question, and the failed one shows its error', () => {
        const { live } = fold('demo-session-dark-mode')
        expect(live.pending?.kind).toBe('question')
        expect(live.pending && decisionQuestionFor(live.pending).options).toHaveLength(2)

        const failed = fold('demo-session-webhooks')
        expect(failed.thread.items.at(-1)?.kind).toBe('error')
        expect(failed.live.status).toBe('failed')
    })
})
