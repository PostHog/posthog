import { resolveNotificationRoute, type TaskLookup } from './notificationRouting'

const TASKS: Record<number, Record<string, string | null>> = {
    2: { 'task-with-report': 'report-1', 'task-without-report': null },
    7: { 'task-in-other-project': 'report-7' },
}

function context(currentProjectId: number | null = 2) {
    return {
        currentProjectId,
        projectIds: [2, 7],
        findTask: jest.fn(async (projectId: number, taskId: string): Promise<TaskLookup> => {
            const projectTasks = TASKS[projectId] ?? {}
            return taskId in projectTasks ? { found: true, reportId: projectTasks[taskId] ?? null } : { found: false }
        }),
    }
}

describe('notification routing', () => {
    test.each([
        [
            'a report in the current project',
            { type: 'report', report_id: 'r1', project_id: 2, notificationKind: 'report_visible' },
            { pathname: '/report/r1', switchToProjectId: null },
        ],
        [
            'a report in another project the user has',
            { type: 'report', report_id: 'r1', project_id: '7' },
            { pathname: '/report/r1', switchToProjectId: 7 },
        ],
        [
            'a report in a project the user cannot open',
            { type: 'report', report_id: 'r1', project_id: 99 },
            { pathname: '/inbox', switchToProjectId: null },
        ],
        [
            'a legacy task linked to a report',
            { taskId: 'task-with-report', taskRunId: 'run-1', notificationKind: 'awaiting' },
            { pathname: '/report/report-1', switchToProjectId: null },
        ],
        [
            'an explicit mobile discussion linked to a report',
            { type: 'task', taskId: 'task-with-report', projectId: 2, notificationKind: 'awaiting' },
            { pathname: '/chat?taskId=task-with-report', switchToProjectId: null },
        ],
        [
            'an explicit task in another project',
            { type: 'task', taskId: 'task-in-other-project', projectId: 7 },
            { pathname: '/chat?taskId=task-in-other-project', switchToProjectId: 7 },
        ],
        [
            'an explicit task without access',
            { type: 'task', taskId: 'missing', projectId: 2 },
            { pathname: '/inbox', switchToProjectId: null },
        ],
        [
            'a task in another project',
            { taskId: 'task-in-other-project', notificationKind: 'completed' },
            { pathname: '/report/report-7', switchToProjectId: 7 },
        ],
        [
            'a task without a report',
            { taskId: 'task-without-report', notificationKind: 'completed' },
            { pathname: '/chat?taskId=task-without-report', switchToProjectId: null },
        ],
        [
            'a task no project has',
            { taskId: 'missing', notificationKind: 'failed' },
            { pathname: '/inbox', switchToProjectId: null },
        ],
    ])('routes %s', async (_name, data, route) => {
        await expect(resolveNotificationRoute(data, context())).resolves.toEqual(route)
    })

    test.each([
        [
            'its own project',
            { taskId: 'task-in-other-project', projectId: 7 },
            { pathname: '/report/report-7', switchToProjectId: 7 },
            [[7, 'task-in-other-project']],
        ],
        [
            'a project the user cannot open',
            { taskId: 'task-with-report', projectId: '99' },
            { pathname: '/inbox', switchToProjectId: null },
            [],
        ],
    ])('a task push that names %s looks up only that project', async (_name, data, route, lookups) => {
        const routeContext = context()

        await expect(resolveNotificationRoute(data, routeContext)).resolves.toEqual(route)
        expect(routeContext.findTask.mock.calls).toEqual(lookups)
    })

    test('a task lookup error falls back to the inbox without trying more projects', async () => {
        const routeContext = context()
        routeContext.findTask.mockRejectedValueOnce(new TypeError('Network request failed'))

        await expect(resolveNotificationRoute({ taskId: 'task-with-report' }, routeContext)).resolves.toEqual({
            pathname: '/inbox',
            switchToProjectId: null,
        })
        expect(routeContext.findTask).toHaveBeenCalledTimes(1)
    })

    test.each([[{ url: 'https://example.com' }], [{ type: 'report' }], [null], ['text']])(
        'ignores an unknown payload %j',
        async (data) => {
            await expect(resolveNotificationRoute(data, context())).resolves.toBeNull()
        }
    )
})
