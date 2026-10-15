import { NotificationPresentation } from './notificationPresentation'

const COMPLETED = { taskId: 'task-1', taskRunId: 'run-1', projectId: 2, notificationKind: 'completed' }

describe('foreground notification sequences', () => {
    test.each(['completed', 'failed', 'cancelled'])(
        'presents a repeated %s outcome once per run',
        (notificationKind) => {
            const policy = new NotificationPresentation()
            const data = { ...COMPLETED, notificationKind }
            expect(
                [0, 45_000, 90_000, 601_000].map((now, index) => policy.shouldPresent(`push-${index}`, data, 'a', now))
            ).toEqual([true, false, false, false])
            expect(policy.shouldPresent('new-run', { ...data, taskRunId: 'run-2' }, 'a', 602_000)).toBe(true)
        }
    )

    test.each(['turn_completed', 'awaiting', 'pull_request_ready'])(
        'preserves distinct %s events while suppressing replay of the same OS notification',
        (notificationKind) => {
            const policy = new NotificationPresentation()
            const data =
                notificationKind === 'pull_request_ready'
                    ? { type: 'report', report_id: 'report-1', project_id: 2, notificationKind }
                    : { ...COMPLETED, notificationKind }
            expect(policy.shouldPresent('first', data, 'a', 0)).toBe(true)
            expect(policy.shouldPresent('first', data, 'a', 1)).toBe(false)
            expect(policy.shouldPresent('second', data, 'a', 2)).toBe(true)
        }
    )

    test.each([
        { ...COMPLETED, notificationKind: 'thread_message', messageId: 'message-1' },
        { type: 'report', report_id: 'report-1', project_id: 2, notificationKind: 'report_visible' },
    ])('collapses a repeated event with a stable identity: %j', (data) => {
        const policy = new NotificationPresentation()
        expect(policy.shouldPresent('first', data, 'a', 0)).toBe(true)
        expect(policy.shouldPresent('replay', data, 'a', 1)).toBe(false)
    })

    test('keeps deduplication scoped to the account and project', () => {
        const policy = new NotificationPresentation()
        expect(policy.shouldPresent('first', COMPLETED, 'a', 0)).toBe(true)
        expect(policy.shouldPresent('other-project', { ...COMPLETED, projectId: 3 }, 'a', 1)).toBe(true)
        expect(policy.shouldPresent('first', COMPLETED, 'b', 2)).toBe(true)
    })

    test('does not infer an event identity for legacy pushes without a project or run', () => {
        const policy = new NotificationPresentation()
        for (const data of [
            { ...COMPLETED, projectId: undefined },
            { ...COMPLETED, taskRunId: undefined },
        ]) {
            expect(policy.shouldPresent(JSON.stringify(data), data, 'a', 0)).toBe(true)
            expect(policy.shouldPresent(`replay-${JSON.stringify(data)}`, data, 'a', 1)).toBe(true)
        }
    })
})
