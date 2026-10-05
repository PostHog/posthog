import { useMocks } from '~/mocks/jest'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

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

export function topic(key: string, categoryType: 'marketing' | 'transactional' = 'marketing'): MessageCategoryApi {
    return {
        id: `topic-${key}`,
        key,
        name: key,
        category_type: categoryType,
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
        created_by: null,
    }
}

export function topicsPage(topics: MessageCategoryApi[]): MockResponse {
    return [200, { count: topics.length, next: null, previous: null, results: topics }]
}

export function useRecipientsApiMocks({
    recipients,
    coverage,
    topics = () => topicsPage([topic('newsletter')]),
}: {
    recipients: (params: URLSearchParams) => MockResponse | Promise<MockResponse>
    coverage: MockResponse
    topics?: () => MockResponse | Promise<MockResponse>
}): void {
    useMocks({
        get: {
            '/api/projects/:team_id/messaging_recipients/': ({ request }) =>
                recipients(new URL(request.url).searchParams),
            '/api/projects/:team_id/messaging_recipients/coverage/': () => coverage,
            '/api/projects/:team_id/messaging_categories/': () => topics(),
        },
    })
}
