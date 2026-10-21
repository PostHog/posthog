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
    it('selects every new suppression rule by default and leaves rate limits for the user to pick', () => {
        expect(defaultSelectedItemIds(ITEMS)).toEqual(['error_message:1'])
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
