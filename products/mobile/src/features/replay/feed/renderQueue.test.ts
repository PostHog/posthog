import { waitFor } from '@testing-library/react-native'

import { type ReplayVideoExport, resolveReplayVideoSource } from '@/api/replayVideo'
import { useAuthStore } from '@/auth/authStore'
import { setSessionTokens } from '@/auth/tokens'

import { type StartRender, startRender, useRenderQueue } from './renderQueue'

jest.mock('@/api/replayVideo', () => ({
    ...jest.requireActual('@/api/replayVideo'),
    resolveReplayVideoSource: jest.fn(),
}))

const exportAsset: ReplayVideoExport = {
    id: 1,
    export_format: 'video/mp4',
    created_at: '2026-01-01T00:00:00Z',
    has_content: true,
    export_context: { session_recording_id: 'recording', timestamp: 0, duration: 20 },
    filename: 'example.mp4',
    expires_after: null,
    exception: null,
}

const render: Omit<StartRender, 'scope'> = {
    spec: { kind: 'full', sessionId: 'recording', durationSeconds: 20 },
    known: [exportAsset],
    allowCreate: false,
    trigger: 'reuse',
    viewport: { width: 400, height: 600 },
}

function signIn(): void {
    setSessionTokens({
        kind: 'oauth',
        accessToken: 'example-token',
        refreshToken: null,
        expiresAt: null,
        grantedScopes: null,
        requestedScopes: null,
    })
}

beforeEach(() => {
    useAuthStore.setState({ host: 'https://app.example.com', projectId: 1 })
    signIn()
})

afterEach(() => {
    setSessionTokens(null)
    useAuthStore.setState({ host: null, projectId: null })
    jest.resetAllMocks()
})

test('drops ready videos and the quota message when the project or account changes', async () => {
    jest.mocked(resolveReplayVideoSource).mockResolvedValue({ uri: 'https://example.com/video.mp4' })
    const scope = useRenderQueue.getState().scope
    startRender({ ...render, scope })
    await waitFor(() => expect(useRenderQueue.getState().jobs['recording:full']?.state.status).toBe('ready'))
    useRenderQueue.setState({ limitMessage: 'Export limit reached' })

    useAuthStore.setState({ projectId: 2 })
    startRender({ ...render, scope })
    expect(useRenderQueue.getState()).toMatchObject({ jobs: {}, limitMessage: null })

    startRender({ ...render, scope: useRenderQueue.getState().scope })
    await waitFor(() => expect(useRenderQueue.getState().jobs['recording:full']?.state.status).toBe('ready'))
    signIn()
    expect(useRenderQueue.getState()).toMatchObject({ jobs: {}, limitMessage: null })
})

test('does not publish a source that finishes resolving after the project changes', async () => {
    let finish: ((source: { uri: string }) => void) | undefined
    jest.mocked(resolveReplayVideoSource).mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                finish = resolve
            })
    )
    startRender({ ...render, scope: useRenderQueue.getState().scope })
    expect(finish).toBeDefined()

    useAuthStore.setState({ projectId: 2 })
    finish?.({ uri: 'https://example.com/video.mp4' })
    await Promise.resolve()
    expect(useRenderQueue.getState().jobs).toEqual({})
})
