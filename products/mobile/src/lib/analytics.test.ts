import { Linking } from 'react-native'

import {
    actionTracker,
    analyticsSessionId,
    setAnalyticsClient,
    setAnalyticsContextProvider,
    setAnalyticsScreenContext,
    track,
    trackScreen,
} from './analytics'
import { openTrackedUrl } from './openTrackedUrl'

describe('mobile analytics attribution', () => {
    const capture = jest.fn()
    const screen = jest.fn()
    let identity = 'account-a'
    let projectId = 1

    beforeEach(() => {
        capture.mockClear()
        screen.mockClear()
        identity = 'account-a'
        projectId = 1
        setAnalyticsContextProvider(() => ({ identity, properties: { project_id: projectId } }))
        setAnalyticsScreenContext({ screen: 'chat', task_id: 'task-a' })
        setAnalyticsClient({ capture, screen, identify: jest.fn(), reset: jest.fn(), getSessionId: () => 'session-a' })
    })

    afterEach(() => {
        jest.restoreAllMocks()
        setAnalyticsClient(null)
        setAnalyticsScreenContext({})
        setAnalyticsContextProvider(() => ({ identity: null, properties: {} }))
    })

    test('custom and screen events retain mobile, project and entity context', () => {
        track('mobile_chat_options_opened', { page: 'model', client_surface: 'web' })
        trackScreen('chat')
        expect(capture).toHaveBeenCalledWith('mobile_chat_options_opened', {
            client_surface: 'mobile',
            project_id: 1,
            screen: 'chat',
            task_id: 'task-a',
            $session_id: 'session-a',
            page: 'model',
        })
        expect(screen).toHaveBeenCalledWith('chat', {
            client_surface: 'mobile',
            project_id: 1,
            screen: 'chat',
            task_id: 'task-a',
            $session_id: 'session-a',
        })
        expect(analyticsSessionId()).toBe('session-a')
    })

    test('a delayed result keeps its original project and is dropped after the account changes', () => {
        const record = actionTracker()
        projectId = 2
        setAnalyticsScreenContext({ screen: 'inbox' })
        record('mobile_session_sent', { run_id: 'run-a' })
        expect(capture).toHaveBeenCalledWith(
            'mobile_session_sent',
            expect.objectContaining({
                project_id: 1,
                task_id: 'task-a',
                run_id: 'run-a',
                screen: 'chat',
                client_action_id: record.actionId,
            })
        )
        identity = 'account-b'
        record('mobile_session_finished')
        expect(capture).toHaveBeenCalledTimes(1)
    })

    test.each([true, false])('link success requires OS acceptance: %s', async (accepted) => {
        let finish!: () => void
        jest.spyOn(Linking, 'openURL').mockImplementation(
            () =>
                new Promise((resolve, reject) => {
                    finish = () => (accepted ? resolve(undefined) : reject(new Error('Example launch failure')))
                })
        )
        const opening = openTrackedUrl('https://example.com/?private=example-value', 'mobile_report_insight_opened', {
            report_id: 'report-a',
        })
        expect(capture).not.toHaveBeenCalled()
        finish()
        await expect(opening).resolves.toBe(accepted)
        expect(capture).toHaveBeenCalledTimes(1)
        expect(capture).toHaveBeenCalledWith(
            accepted ? 'mobile_report_insight_opened' : 'mobile_link_launch_failed',
            expect.objectContaining({ report_id: 'report-a', client_surface: 'mobile' })
        )
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example-value')
    })
})
