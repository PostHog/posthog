import { useMocks } from '~/mocks/jest'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

export type MockResponse = [number, unknown]

export function recipient(email: string, overrides: Partial<RecipientApi> = {}): RecipientApi {
    return {
        email,
        all_marketing: 'NO_PREFERENCE',
        topics: {},
        suppression: null,
        persons: [],
        person_count: 0,
        last_sent_at: null,
        preferences_updated_at: null,
        ...overrides,
    }
}

export function useRecipientsApiMocks({
    recipients,
    coverage,
}: {
    recipients: (params: URLSearchParams) => MockResponse | Promise<MockResponse>
    coverage: MockResponse
}): void {
    useMocks({
        get: {
            '/api/projects/:team_id/messaging_recipients/': ({ request }) =>
                recipients(new URL(request.url).searchParams),
            '/api/projects/:team_id/messaging_recipients/coverage/': () => coverage,
        },
    })
}
