import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { dataCheckText } from './dataCheckText'

const passed: InsightDataCheckApi = {
    key: 'bot_traffic',
    level: 'passed',
    skip_reason: null,
    method: 'sampled',
    events: 0,
    share: 0,
    scaled: false,
    action: null,
    top_events: [],
    top_hosts: [],
    top_bots: [],
}

describe('dataCheckText', () => {
    it.each<[string, Partial<InsightDataCheckApi>, boolean, string, string | null]>([
        [
            'a skipped check with its reason',
            { level: 'skipped', skip_reason: 'read_limit', events: null, share: null },
            false,
            'Not checked, because it would read more data than it is allowed',
            null,
        ],
        [
            'a passed check that found a few events, from a sample',
            { events: 1234, share: 0.001, scaled: true },
            false,
            'Almost no bots or crawlers found (about 1,234 events)',
            null,
        ],
        [
            'internal users on an insight that filters them out',
            { key: 'internal_users', method: 'counted' },
            true,
            'Internal and test users are filtered out',
            null,
        ],
        [
            'a finding from a sample, without the filter on',
            { level: 'problem', events: 4000, share: 0.4, scaled: true, action: 'open_filter_settings' },
            false,
            'About 40% of these events came from bots and crawlers',
            'In the internal and test users filter, add "Traffic type is not Bot or AI Agent", and turn that filter on for this insight.',
        ],
        [
            'a finding too small for a share, with the filter on',
            { key: 'local_development', level: 'warning', events: 60, share: 0.002, action: 'open_filter_settings' },
            true,
            '60 of these events came from local development',
            'Send local traffic to a separate project, or exclude localhost in the internal and test users filter.',
        ],
        [
            'internal users that turning the filter on removes',
            { key: 'internal_users', level: 'warning', events: 80, share: 0.08, action: 'filter_internal_users' },
            false,
            '8% of these events came from internal and test users',
            'Turn on the internal and test users filter for this insight.',
        ],
    ])('words %s', (_name, check, filtersTestAccounts, result, fix) => {
        expect(dataCheckText({ ...passed, ...check }, filtersTestAccounts)).toMatchObject({ result, fix })
    })
})
