import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import type { PreflightStatus } from '~/types'
import { Region } from '~/types'

import { appendTicketMetadata, feedbackContextUrl } from './ticketMetadata'

describe('ticketMetadata', () => {
    const originalAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = { current_team: { id: 2 } } as unknown as typeof window.POSTHOG_APP_CONTEXT
    })

    afterAll(() => {
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    it('links feedback to the answer trace when one is available', () => {
        expect(
            feedbackContextUrl({
                sessionId: 'task-1',
                sessionKind: 'task',
                traceId: 'trace-1',
                run: { taskId: 'task-1' },
            })
        ).toBe('http://localhost/project/2/ai-observability/traces/trace-1')
    })

    it.each([Region.US, Region.EU])(
        'links Cloud answer traces to the telemetry project from a %s customer project',
        (region) => {
            window.POSTHOG_APP_CONTEXT = { current_team: { id: 4242 } } as unknown as typeof window.POSTHOG_APP_CONTEXT
            preflightLogic.mount()
            preflightLogic.actions.loadPreflightSuccess({ cloud: true, region } as PreflightStatus)

            expect(
                feedbackContextUrl({
                    sessionId: 'task-1',
                    sessionKind: 'task',
                    traceId: 'trace-1',
                    run: { taskId: 'task-1', runId: 'run-1' },
                })
            ).toBe('https://us.posthog.com/project/2/ai-observability/traces/trace-1')
            expect(
                feedbackContextUrl({
                    sessionId: 'task-1',
                    sessionKind: 'task',
                    traceId: null,
                    run: { taskId: 'task-1', runId: 'run-1' },
                })
            ).toBe('http://localhost/project/4242/ai?task=task-1&runId=run-1')
        }
    )

    it('falls back to the specific task run when the answer has no trace', () => {
        expect(
            feedbackContextUrl({
                sessionId: 'task-1',
                sessionKind: 'task',
                traceId: null,
                run: { taskId: 'task-1', runId: 'run-1' },
            })
        ).toBe('http://localhost/project/2/ai?task=task-1&runId=run-1')
    })

    it('falls back to the conversation when there is no trace or run', () => {
        expect(feedbackContextUrl({ sessionId: 'conversation-1', sessionKind: 'conversation', traceId: null })).toBe(
            'http://localhost/project/2/ai?chat=conversation-1'
        )
    })

    it('adds the trace link to support tickets without dropping the identifiers', () => {
        expect(
            appendTicketMetadata('Please investigate', {
                sessionId: 'task-1',
                sessionKind: 'task',
                traceId: 'trace-1',
                run: { taskId: 'task-1', runId: 'run-1' },
            })
        ).toBe(
            'Please investigate\n\n----\nTask ID: task-1\nTrace ID: trace-1\nRun ID: run-1\nAnswer trace: http://localhost/project/2/ai-observability/traces/trace-1'
        )
    })
})
