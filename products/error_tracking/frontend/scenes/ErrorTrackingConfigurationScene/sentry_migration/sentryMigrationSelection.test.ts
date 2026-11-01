import type { SentryMigrationItemApi } from '../../../generated/api.schemas'
import { defaultSelectedItemIds, toggleItemSelection } from './sentryMigrationSelection'

function item(id: string, overrides: Partial<SentryMigrationItemApi> = {}): SentryMigrationItemApi {
    return {
        id,
        category: 'error_message',
        sentry_setting: 'Error message filter',
        sentry_value: '*boom*',
        fit: 'good',
        note: null,
        suppression_rule_filters: null,
        rate_limit: null,
        built_in_filter: null,
        already_in_posthog: false,
        ...overrides,
    }
}

const ITEMS = [
    item('rate_limit:a', { category: 'rate_limit', rate_limit: { value: 100, bucket_size_minutes: 60 } }),
    item('rate_limit:b', { category: 'rate_limit', rate_limit: { value: 200, bucket_size_minutes: 15 } }),
    item('error_message:1'),
    item('error_message:2', { already_in_posthog: true }),
    item('inbound_filter:blocked-ips', { category: 'inbound_filter', fit: 'unsupported' }),
]

describe('sentryMigrationSelection', () => {
    it.each([
        ['selects every new rule and the first rate limit', ITEMS, ['rate_limit:a', 'error_message:1']],
        [
            'prefers the rate limit whose window converts exactly',
            [
                item('rate_limit:a', {
                    category: 'rate_limit',
                    fit: 'partial',
                    rate_limit: { value: 1, bucket_size_minutes: 15 },
                }),
                ...ITEMS.slice(1),
            ],
            ['rate_limit:b', 'error_message:1'],
        ],
        [
            'selects no rate limit when the project already has one of them',
            [
                item('rate_limit:a', {
                    category: 'rate_limit',
                    already_in_posthog: true,
                    rate_limit: { value: 100, bucket_size_minutes: 60 },
                }),
                ...ITEMS.slice(1),
            ],
            ['error_message:1'],
        ],
    ])('default selection %s', (_name, items, expected) => {
        expect(defaultSelectedItemIds(items)).toEqual(expected)
    })

    it.each([
        [
            'selecting a second rate limit replaces the first',
            ['rate_limit:a', 'error_message:1'],
            'rate_limit:b',
            ['error_message:1', 'rate_limit:b'],
        ],
        ['deselects a selected item', ['rate_limit:a', 'error_message:1'], 'error_message:1', ['rate_limit:a']],
        ['ignores an item already in PostHog', ['error_message:1'], 'error_message:2', ['error_message:1']],
        ['ignores an unsupported item', [], 'inbound_filter:blocked-ips', []],
    ])('%s', (_name, selected, toggled, expected) => {
        expect(toggleItemSelection(ITEMS, selected, toggled)).toEqual(expected)
    })
})
