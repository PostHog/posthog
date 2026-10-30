import { routeForPath } from './mobileTelemetry'

describe('routeForPath', () => {
    test.each([
        ['/api/projects/2/insights/aB3dE9fG/', '/api/projects/:id/insights/:id/'],
        ['/api/projects/2/tasks/models/', '/api/projects/:id/tasks/models/'],
        ['/api/projects/2/tasks/@me/config/', '/api/projects/:id/tasks/@me/config/'],
        [
            '/api/projects/2/tasks/0b9c6f1e-3c1a-4d2b-9a8e-1f2e3d4c5b6a/runs/7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f/logs/',
            '/api/projects/:id/tasks/:id/runs/:id/logs/',
        ],
        [
            '/api/projects/2/signals/reports/available_reviewers/',
            '/api/projects/:id/signals/reports/available_reviewers/',
        ],
        ['/api/projects/2/signals/reports/report-1/state/', '/api/projects/:id/signals/reports/:id/state/'],
        ['/api/projects/2/error_tracking/query/issue_events/', '/api/projects/:id/error_tracking/query/issue_events/'],
        ['/api/projects/2/session_recordings/abc123def?limit=5', '/api/projects/:id/session_recordings/:id'],
        ['/api/organizations/some-org/', '/api/organizations/:id/'],
        ['/api/users/@me/push_tokens/unregister/', '/api/users/@me/push_tokens/unregister/'],
    ])('%s is reported as %s', (path, route) => {
        expect(routeForPath(path)).toBe(route)
    })
})
