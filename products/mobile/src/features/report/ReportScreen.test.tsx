import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState } from 'react-native'

import { setAuthProvider } from '@/api/client'
import { useDemoMode } from '@/demo/demoMode'
import { reportFixture } from '@/model/adapters/testFixtures'

import { ReportScreen } from './ReportScreen'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock('expo-notifications', () => ({}))
jest.mock('expo-router', () => ({
    useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]),
    useIsFocused: () => true,
    useRouter: () => ({ push: jest.fn(), setParams: jest.fn(), canGoBack: () => false, replace: jest.fn() }),
}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const REPORT = reportFixture()
const EXISTING = { uuid: 'existing-user', first_name: 'Existing', last_name: 'Reviewer', email: 'existing@example.com' }
const ADDED = { uuid: 'added-user', first_name: 'Added', last_name: 'Reviewer', email: 'added@example.com' }

describe('ReportScreen reviewers', () => {
    test.each(['loaded', 'retry'] as const)(
        'keeps an existing reviewer beyond the first activity page when adding another (%s)',
        async (scenario) => {
            AppState.currentState = 'active'
            const appListener = jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: () => undefined })
            useDemoMode.getState().setEnabled(false)
            setAuthProvider({
                getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
                refreshAccessToken: async () => null,
            })
            const assignments: unknown[] = []
            let finishReviewerRead: ((response: Response) => void) | undefined
            let heldRead = false
            let content = [{ user_uuid: EXISTING.uuid, github_login: null, user: EXISTING }]
            globalThis.fetch = jest.fn(async (input, init) => {
                const url = new URL(String(input))
                const assignment = { id: 'assignment', type: 'suggested_reviewers', content }
                let body: unknown
                if (init?.method === 'PUT') {
                    const saved = JSON.parse(String(init.body)) as { content: { user_uuid: string }[] }
                    assignments.push(saved)
                    content = saved.content.map(({ user_uuid }) => ({
                        user_uuid,
                        github_login: null,
                        user: user_uuid === EXISTING.uuid ? EXISTING : ADDED,
                    }))
                    body = assignment
                } else if (url.pathname.endsWith('/available_reviewers/')) {
                    body = {
                        [EXISTING.uuid]: { name: 'Existing Reviewer', email: EXISTING.email },
                        [ADDED.uuid]: { name: 'Added Reviewer', email: ADDED.email },
                    }
                } else if (url.pathname.endsWith('/artefacts/')) {
                    if (scenario === 'retry' && url.searchParams.get('offset') === '100' && !heldRead) {
                        heldRead = true
                        return new Promise<Response>((resolve) => {
                            finishReviewerRead = resolve
                        })
                    }
                    body =
                        url.searchParams.get('offset') === '100'
                            ? { count: 101, next: null, results: [assignment] }
                            : {
                                  count: 101,
                                  next: `${url.origin}${url.pathname}?limit=100&offset=100`,
                                  results: Array.from({ length: 100 }, (_, index) => ({
                                      id: `note-${index}`,
                                      type: 'note',
                                      content: { text: 'A note' },
                                      created_at: REPORT.updated_at,
                                  })),
                              }
                } else if (url.pathname.endsWith('/page/')) {
                    body = { lead: '', impact_sentence: '', evidence: [], impact_numbers: [], last_seen: null }
                } else if (url.pathname.endsWith('/signals/')) {
                    body = { signals: [] }
                } else if (url.pathname.endsWith('/read_state/')) {
                    body = { states: { [REPORT.id]: true } }
                } else if (url.pathname.endsWith('/reports/')) {
                    body = { count: 1, next: null, results: [REPORT] }
                } else {
                    body = REPORT
                }
                return new Response(JSON.stringify(body), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            }) as typeof fetch
            const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
            const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
                <QueryClientProvider client={client}>{children}</QueryClientProvider>
            )
            const view = render(<ReportScreen reportId={REPORT.id} from="inbox" />, { wrapper })
            try {
                await waitFor(() => expect(screen.getByTestId('report-owner-chip')).toBeTruthy())
                fireEvent.press(screen.getByTestId('report-owner-chip'))
                if (scenario === 'retry') {
                    await waitFor(() => expect(screen.getByLabelText('Loading the assignees')).toBeTruthy())
                    expect(screen.queryByTestId('assignee-done')).toBeNull()
                    await act(async () => {
                        finishReviewerRead?.(
                            new Response(JSON.stringify({ detail: 'Unavailable' }), {
                                status: 503,
                                headers: { 'Content-Type': 'application/json' },
                            })
                        )
                    })
                    await waitFor(() => expect(screen.getByTestId('assignee-load-error')).toBeTruthy())
                    expect(screen.queryByTestId('assignee-done')).toBeNull()
                    expect(assignments).toEqual([])
                    fireEvent.press(screen.getByText('Try again'))
                }
                await waitFor(() =>
                    expect(screen.getByTestId(`assignee-${EXISTING.uuid}`).props.accessibilityState.checked).toBe(true)
                )
                fireEvent.press(screen.getByTestId(`assignee-${ADDED.uuid}`))
                await act(async () => fireEvent.press(screen.getByTestId('assignee-done')))
                await waitFor(() =>
                    expect(assignments).toEqual([
                        { content: [{ user_uuid: EXISTING.uuid }, { user_uuid: ADDED.uuid }] },
                    ])
                )
            } finally {
                view.unmount()
                client.clear()
                appListener.mockRestore()
                setAuthProvider(null)
            }
        }
    )
})
