import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, waitFor } from '@testing-library/react-native'

import { setAuthProvider } from '@/api/client'
import type { LiveEventRow } from '@/model/live'

import { LiveEventProperties } from './LiveEventProperties'

const EVENT: LiveEventRow = {
    id: 'event-1',
    event: 'file_uploaded',
    label: 'file_uploaded',
    kind: 'other',
    distinctId: 'person-1',
    place: '/files',
    url: 'https://example.com/files',
    sessionId: null,
    at: 0,
}
const SCOPE = { host: 'https://app.example.com', projectId: 2 }

function response(body: unknown, status = 200): Response {
    return {
        ok: status === 200,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('LiveEventProperties', () => {
    let client: QueryClient
    const originalFetch = globalThis.fetch

    beforeEach(() => {
        client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
        setAuthProvider({
            getAuth: () => ({ ...SCOPE, accessToken: 'fake-token', session: 1 }),
            refreshAccessToken: async () => null,
        })
    })

    afterEach(() => {
        client.clear()
        setAuthProvider(null)
        globalThis.fetch = originalFetch
    })

    function screen(event = EVENT, scope: typeof SCOPE | null = SCOPE, active = true): React.JSX.Element {
        return (
            <QueryClientProvider client={client}>
                <LiveEventProperties event={event} scope={scope} active={active} />
            </QueryClientProvider>
        )
    }

    test('loads on opening and never displays another event or project’s cached properties', async () => {
        let finish: (result: Response) => void = () => undefined
        const fetch = jest.fn(
            (_url: string | URL | Request, _init?: RequestInit) =>
                new Promise<Response>((resolve) => {
                    finish = resolve
                })
        )
        globalThis.fetch = fetch
        const view = render(screen(EVENT, SCOPE, false))
        expect(fetch).not.toHaveBeenCalled()
        view.rerender(screen())
        expect(view.getByLabelText('Loading custom properties')).toBeTruthy()
        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
        expect(fetch.mock.calls[0]?.[0]).toBe('https://app.example.com/api/projects/2/events/event-1/')
        await act(async () => finish(response({ properties: { plan: 'pro', $browser: 'Safari' } })))
        expect(await view.findByText('pro')).toBeTruthy()
        expect(view.queryByText('$browser')).toBeNull()
        view.rerender(screen({ ...EVENT, id: 'event-2' }))
        expect(view.queryByText('pro')).toBeNull()
        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
        await act(async () => finish(response({ properties: { plan: 'free' } })))
        expect(await view.findByText('free')).toBeTruthy()
        view.rerender(screen(EVENT, { ...SCOPE, projectId: 3 }))
        expect(view.queryByText('pro')).toBeNull()
        expect(view.queryByText('free')).toBeNull()
        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
        await act(async () => finish(response({ properties: {} })))
        expect(await view.findByText('No custom properties on this event.')).toBeTruthy()
    })

    test('shows a retryable error instead of treating an unsuccessful read as an empty event', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue(response({ detail: 'Unavailable' }, 403))
        const view = render(screen())
        expect(await view.findByText("Couldn't load properties.")).toBeTruthy()
        expect(view.queryByText('No custom properties on this event.')).toBeNull()
        let finish: (result: Response) => void = () => undefined
        globalThis.fetch = jest.fn(
            () =>
                new Promise<Response>((resolve) => {
                    finish = resolve
                })
        )
        fireEvent.press(view.getByTestId('live-event-properties-retry'))
        await waitFor(() => expect(view.getByLabelText('Loading custom properties')).toBeTruthy())
        expect(view.queryByTestId('live-event-properties-retry')).toBeNull()
        await act(async () => finish(response({ properties: { enabled: false } })))
        expect(await view.findByText('false')).toBeTruthy()
    })

    test('demo properties render without sending a request', async () => {
        globalThis.fetch = jest.fn()
        const view = render(screen(EVENT, null))
        expect(await view.findByText('pro')).toBeTruthy()
        expect(view.getByText('false')).toBeTruthy()
        expect(globalThis.fetch).not.toHaveBeenCalled()
    })
})
