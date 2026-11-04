import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { dataCheckText, filterCheckParts, removesBotTraffic, repeatedEventsTextOf } from './dataCheckText'
import type { FilterCheckParts } from './dataCheckText'

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
    distinct_hosts: null,
    top_bots: [],
    distinct_bots: null,
    removed_by_filter: null,
    missed_by_filter: null,
    top_emails: [],
    distinct_emails: null,
    filter_to_add: null,
}

const BOT_RULE = { key: '$virt_traffic_type', type: 'event', operator: 'is_not', value: ['AI Agent', 'Bot'] }

describe('dataCheckText', () => {
    it.each<[string, Partial<InsightDataCheckApi>, boolean, boolean, string]>([
        [
            'a skipped check with its reason',
            { level: 'skipped', skip_reason: 'read_limit', events: null, share: null },
            false,
            false,
            'Not checked, because it would read more data than it is allowed',
        ],
        [
            'a passed check that found a few events, from a sample',
            { events: 1234, share: 0.001, scaled: true },
            false,
            false,
            'Almost none (about 1,234 events)',
        ],
        [
            'a passed localhost check where nearly every event is local',
            { key: 'local_development', method: 'counted', events: 950, share: 0.95 },
            false,
            false,
            '95% of these events, so they come from your app',
        ],
        [
            'internal users on an insight that filters them out',
            { key: 'internal_users', method: 'counted' },
            true,
            false,
            'Filtered out',
        ],
        [
            'internal users on an insight that filters them out, with team emails the filter misses',
            { key: 'internal_users', method: 'counted', missed_by_filter: 40, distinct_emails: 32 },
            true,
            false,
            'Filtered out, except 32 users',
        ],
        [
            'a finding from a sample',
            { level: 'problem', events: 4000, share: 0.4, scaled: true },
            false,
            false,
            'About 40% of these events',
        ],
        [
            'a finding too small for a share',
            { key: 'local_development', level: 'warning', method: 'counted', events: 60, share: 0.001 },
            false,
            false,
            '60 of these events',
        ],
        [
            'bots on an insight whose internal and test users filter removes them',
            { level: 'skipped', skip_reason: 'filtered_by_traffic_type', events: null, share: null },
            true,
            true,
            'Filtered out',
        ],
        [
            'bots on an insight with its own traffic type filter',
            { level: 'skipped', skip_reason: 'filtered_by_traffic_type', events: null, share: null },
            true,
            false,
            "Not checked, because this insight's filters already choose which traffic types to keep",
        ],
    ])('words the result of %s', (_name, check, filtersTestAccounts, filterRemovesBots, expected) => {
        expect(dataCheckText({ ...passed, ...check }, filtersTestAccounts, filterRemovesBots).result).toEqual(expected)
    })

    it.each<[string, Partial<InsightDataCheckApi>, boolean, boolean, FilterCheckParts]>([
        [
            'internal users the filter catches while the insight leaves it off, and team emails it misses',
            {
                key: 'internal_users',
                level: 'problem',
                events: 810,
                share: 0.81,
                removed_by_filter: 620,
                missed_by_filter: 190,
                top_emails: ['sam@example.com', 'qa@example.com'],
                distinct_emails: 14,
                filter_to_add: { key: 'email', type: 'person', operator: 'is_not', value: ['qa@example.com'] },
            },
            false,
            false,
            {
                caught: "Your filter catches 62% of these events, but it's off for this insight.",
                missed: {
                    count: 14,
                    noun: 'user',
                    examples: ['sam@example.com', 'qa@example.com'],
                    fallback: 'Some users',
                    predicate: "have emails that match your team, but none of your filter's rules remove them.",
                    explanation:
                        "An email matches your team when it's on the same domain as someone in your organization, " +
                        'or looks like a test account, such as test@ or name+qa@.',
                },
            },
        ],
        [
            'bots a traffic type rule catches while the insight leaves the filter off',
            {
                level: 'warning',
                events: 150,
                share: 0.14,
                top_bots: ['Googlebot'],
                distinct_bots: 1,
                filter_to_add: BOT_RULE,
            },
            false,
            true,
            { caught: "Your filter catches this bot traffic, but it's off for this insight.", missed: null },
        ],
        [
            'bots that get past a filter with no traffic type rule',
            {
                level: 'warning',
                events: 150,
                share: 0.14,
                top_bots: ['Googlebot', 'Ahrefs'],
                distinct_bots: 5,
                filter_to_add: BOT_RULE,
            },
            true,
            false,
            {
                caught: null,
                missed: {
                    count: 5,
                    noun: 'bot',
                    examples: ['Googlebot', 'Ahrefs'],
                    fallback: 'Bot events',
                    predicate: "aren't caught by your internal and test users filter.",
                    explanation: null,
                },
            },
        ],
        ['a check that found nothing', { key: 'local_development' }, true, false, { caught: null, missed: null }],
    ])('splits %s', (_name, check, filtersTestAccounts, filterRemovesBots, expected) => {
        expect(filterCheckParts({ ...passed, ...check }, filtersTestAccounts, filterRemovesBots)).toEqual(expected)
    })

    it.each<[string[], string]>([
        [['$pageview', 'signed_up'], 'Pageview and signed_up events are sent twice'],
        [[], 'Some events are sent twice'],
    ])('names the repeated events %j by their labels', (events, expected) => {
        expect(repeatedEventsTextOf({ ...passed, key: 'duplicate_events', top_events: events }).found).toContain(
            expected
        )
    })

    const trafficRule = (operator: string, value: string | string[]): Record<string, unknown> => ({
        key: '$virt_traffic_type',
        type: 'event',
        operator,
        value,
    })

    it.each<[string, Record<string, unknown>[], boolean]>([
        ['one rule that excludes both types', [trafficRule('is_not', ['Bot', 'AI Agent'])], true],
        [
            'two rules that each exclude one type',
            [trafficRule('is_not', 'Bot'), trafficRule('is_not', ['AI Agent'])],
            true,
        ],
        ['a rule that excludes only AI agents', [trafficRule('is_not', ['AI Agent'])], false],
        ['a rule that keeps only bots', [trafficRule('exact', ['Bot', 'AI Agent'])], false],
    ])('knows whether the filter removes bot traffic with %s', (_name, rules, expected) => {
        expect(removesBotTraffic(rules)).toBe(expected)
    })
})
