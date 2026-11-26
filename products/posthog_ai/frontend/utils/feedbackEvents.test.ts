import posthog from 'posthog-js'

import { captureTurnFeedbackText } from './feedbackEvents'

describe('feedbackEvents', () => {
    const originalAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = { current_team: { id: 2 } } as unknown as typeof window.POSTHOG_APP_CONTEXT
    })

    afterAll(() => {
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    it('links feedback to the answer trace', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)

        captureTurnFeedbackText('task-1', 'trace-1', 'The answer was wrong', 0, { taskId: 'task-1', runId: 'run-1' })

        expect(capture).toHaveBeenCalledWith(
            '$ai_feedback',
            expect.objectContaining({
                $ai_trace_id: 'trace-1',
                ai_context_url: 'http://localhost/project/2/ai-observability/traces/trace-1',
                task_id: 'task-1',
                run_id: 'run-1',
            })
        )
        capture.mockRestore()
    })

    it('links feedback to the run when the answer has no trace', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)

        captureTurnFeedbackText('task-1', null, 'The answer was wrong', 0, { taskId: 'task-1', runId: 'run-1' })

        expect(capture).toHaveBeenCalledWith(
            '$ai_feedback',
            expect.objectContaining({
                ai_context_url: 'http://localhost/project/2/ai?task=task-1&runId=run-1',
                task_id: 'task-1',
                run_id: 'run-1',
            })
        )
        expect(capture.mock.calls[0][1]).not.toHaveProperty('$ai_trace_id')
        capture.mockRestore()
    })
})
