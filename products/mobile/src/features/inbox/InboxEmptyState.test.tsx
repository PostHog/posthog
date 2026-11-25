import { fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import * as Clipboard from 'expo-clipboard'
import * as WebBrowser from 'expo-web-browser'

import { ApiError } from '@/api/client'
import type { InboxStatusApi } from '@/api/inboxStatus'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'

import { InboxEmptyState } from './InboxEmptyState'
import { inboxSetupUrl } from './inboxSetupState'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('expo-web-browser', () => ({ openBrowserAsync: jest.fn() }))
jest.mock('expo-clipboard', () => ({ setStringAsync: jest.fn() }))

const mockScope = { host: 'https://eu.posthog.com', projectId: 42 }
const status: InboxStatusApi = {
    setup_state: 'active',
    has_report_history: false,
    first_report_status: null,
    can_configure: true,
}

describe('self-driving empty inbox', () => {
    beforeEach(() => jest.clearAllMocks())

    test.each([
        [{ setup_state: 'not_started' }, 'Set up self-driving'],
        [{ setup_state: 'in_progress' }, 'Finish setting up self-driving'],
        [{ setup_state: 'paused', has_report_history: true }, 'Self-driving is paused'],
        [{ setup_state: 'ai_disabled' }, 'AI data processing is off'],
        [{ first_report_status: 'running' }, 'Looking for your first report'],
        [{ first_report_status: 'no_data' }, 'Waiting for product data'],
        [{ first_report_status: 'no_actionable_finding' }, 'Your first investigation is complete'],
        [{ has_report_history: true }, 'Nothing needs you right now'],
        [{ first_report_status: 'report_created' }, 'Nothing needs you right now'],
        [{}, 'Waiting for your first report'],
    ] as [Partial<InboxStatusApi>, string][])('explains the project state %j', (fields, title) => {
        render(<InboxEmptyState status={successQuery({ ...status, ...fields })} onRefresh={jest.fn()} />)
        expect(screen.getByText(title)).toBeTruthy()
    })

    test.each([
        loadingQuery<InboxStatusApi>(),
        errorQuery<InboxStatusApi>(new Error('Offline')),
        errorQuery<InboxStatusApi>(new ApiError(403, {})),
    ])('does not claim setup is missing when status is unknown', (query) => {
        render(<InboxEmptyState status={query} onRefresh={jest.fn()} />)
        expect(screen.queryByText('Continue on web')).toBeNull()
        expect(screen.queryByText('Nothing needs you right now')).toBeNull()
    })

    test('opens setup in the project region and refreshes when the browser closes', async () => {
        jest.mocked(WebBrowser.openBrowserAsync).mockResolvedValue({
            type: WebBrowser.WebBrowserResultType?.CANCEL ?? 'cancel',
        } as WebBrowser.WebBrowserResult)
        const refetch = jest.fn()
        const refresh = jest.fn()
        render(
            <InboxEmptyState
                status={successQuery({ ...status, setup_state: 'not_started' }, { refetch })}
                onRefresh={refresh}
            />
        )
        fireEvent.press(screen.getByText('Continue on web'))
        await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
        expect(refetch).toHaveBeenCalledTimes(1)
        const url = new URL(jest.mocked(WebBrowser.openBrowserAsync).mock.calls[0]?.[0] ?? '')
        expect(url.origin + url.pathname).toBe('https://eu.posthog.com/project/42/inbox/activate')
        expect(url.searchParams.get('mobile_return')).toBeTruthy()
    })

    test('lets a viewer share the project setup link with an admin', async () => {
        jest.mocked(Clipboard.setStringAsync).mockResolvedValue(true)
        render(
            <InboxEmptyState
                status={successQuery({ ...status, setup_state: 'not_started', can_configure: false })}
                onRefresh={jest.fn()}
            />
        )
        expect(screen.getByText(/Ask a project admin/)).toBeTruthy()
        fireEvent.press(screen.getByText('Copy setup link'))
        await waitFor(() => expect(screen.getByText(/Link copied/)).toBeTruthy())
        expect(jest.mocked(Clipboard.setStringAsync).mock.calls[0]?.[0] ?? '').toContain(
            'https://eu.posthog.com/project/42/inbox/activate?'
        )
    })

    test.each(['javascript:alert(1)', 'https://user:secret@example.com', 'http://example.com'])(
        'rejects unsafe web handoffs: %s',
        (host) => {
            expect(inboxSetupUrl({ ...mockScope, host }, 'not_started')).toBeNull()
        }
    )
})
