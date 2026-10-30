type MobileTelemetryModule = typeof import('./mobileTelemetry')
type FeatureFlagsModule = typeof import('./featureFlags')
type Log = Parameters<MobileTelemetryModule['initMobileTelemetry']>[2]

function loadEnabledTelemetry(host: string, log: Log): MobileTelemetryModule {
    let loaded: MobileTelemetryModule | undefined
    jest.isolateModules(() => {
        const { FEATURE_FLAGS, setFeatureFlags } = jest.requireActual<FeatureFlagsModule>('./featureFlags')
        setFeatureFlags({ [FEATURE_FLAGS.networkObservability]: true })
        loaded = jest.requireActual<MobileTelemetryModule>('./mobileTelemetry')
    })
    if (!loaded) {
        throw new Error('mobile telemetry module did not load')
    }
    loaded.initMobileTelemetry('phc_test', host, log)
    return loaded
}

describe('mobileTelemetry', () => {
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
    ])('reports %s as route %s', (path, route) => {
        const { routeForPath } = jest.requireActual<MobileTelemetryModule>('./mobileTelemetry')
        expect(routeForPath(path)).toBe(route)
    })

    test.each([
        ['an export host that is not a URL', 'us.i.posthog.com', jest.fn()],
        [
            'a logger that throws on a server error',
            'https://us.i.posthog.com',
            jest.fn(() => {
                throw new Error('logger failed')
            }),
        ],
    ])('returns the response unchanged with %s', async (_, host, log) => {
        const { instrumentApiRequest } = loadEnabledTelemetry(host, log)
        const response = { status: 503 } as Response

        await expect(instrumentApiRequest('/api/users/@me/', 'GET', () => Promise.resolve(response))).resolves.toBe(
            response
        )
    })

    test('does not report a cancelled request as a failure', async () => {
        const log = jest.fn()
        const { instrumentApiRequest } = loadEnabledTelemetry('https://us.i.posthog.com', log)
        const aborted = Object.assign(new Error('The operation was aborted'), { name: 'AbortError' })

        await expect(instrumentApiRequest('/api/users/@me/', 'GET', () => Promise.reject(aborted))).rejects.toBe(
            aborted
        )
        expect(log).not.toHaveBeenCalled()
    })
})
