import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import type {
    InsightDataCheckApi,
    InsightDataCheckKeyEnumApi,
    InsightDataCheckSkipReasonEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

export interface DataCheckText {
    /** The same whatever the result, so a row reads as the check it is. */
    name: string
    /** The result, short enough to sit under the name. */
    result: string
}

const TRAFFIC_TYPE_PROPERTY = '$virt_traffic_type'
// The traffic types the bot check counts, as the backend's CRAWLER_TRAFFIC_TYPES lists them.
const CRAWLER_TRAFFIC_TYPES = ['Bot', 'AI Agent']

export function removesBotTraffic(
    rules: readonly { key?: string; type?: string; operator?: unknown; value?: unknown }[]
): boolean {
    // The filter's rules all apply, so values excluded by separate rules add up.
    const excluded = rules
        .filter((rule) => rule.key === TRAFFIC_TYPE_PROPERTY && rule.type === 'event' && rule.operator === 'is_not')
        .flatMap((rule) => (Array.isArray(rule.value) ? rule.value : [rule.value]))
    return CRAWLER_TRAFFIC_TYPES.every((type) => excluded.includes(type))
}

/** The checks that the project's internal and test users filter answers. */
export const FILTER_CHECK_KEYS: readonly InsightDataCheckKeyEnumApi[] = [
    'internal_users',
    'local_development',
    'bot_traffic',
]

export const DATA_CHECK_NAMES: Record<InsightDataCheckKeyEnumApi, string> = {
    internal_users: 'Internal and test users',
    local_development: 'Localhost events',
    bot_traffic: 'Bot and crawler traffic',
    duplicate_events: 'Events sent twice',
}

const SKIP_REASONS: Record<InsightDataCheckSkipReasonEnumApi, string> = {
    too_many_events: 'the days checked hold too many events to count',
    read_limit: 'it would read more data than it is allowed',
    time_limit: 'it took longer than it is allowed',
    memory_limit: 'it needed more memory than it is allowed',
    too_few_sampled_events: 'the sample has too few events',
    filtered_by_traffic_type: 'this insight already filters on traffic type',
    hidden_property: 'a property it reads is hidden from you',
    invalid_filter: "the project's internal and test users filter cannot run",
}

function eventCount(check: InsightDataCheckApi): string {
    const count = humanFriendlyNumber(check.events ?? 0)
    return check.scaled ? `about ${count}` : count
}

/** The examples, then how many more there are, such as "a, b and 3 other hosts". */
function examplesOf(examples: string[], total: number | null, other: string): string | null {
    if (!examples.length) {
        return null
    }
    const others = (total ?? examples.length) - examples.length
    if (others > 0) {
        return `${examples.join(', ')} and ${pluralize(others, other)}`
    }
    const last = examples[examples.length - 1]
    return examples.length > 1 ? `${examples.slice(0, -1).join(', ')} and ${last}` : last
}

function shareOf(check: InsightDataCheckApi, part: number): number | null {
    const share = check.share !== null && check.events ? (check.share * part) / check.events : null
    return share !== null && share >= 0.01 ? Math.round(share * 100) : null
}

export interface FilterCheckParts {
    /** Set when the project's filter catches these events but the insight leaves the filter off. */
    caught: string | null
    missed: { count: number; noun: string; examples: string[]; fallback: string; excludeLabel: string } | null
}

const NOTHING: FilterCheckParts = { caught: null, missed: null }

function isFinding(check: InsightDataCheckApi): boolean {
    return check.level === 'warning' || check.level === 'problem'
}

function internalUsersParts(check: InsightDataCheckApi, filtersTestAccounts: boolean): FilterCheckParts {
    const removed = check.removed_by_filter
    const removedShare = removed ? shareOf(check, removed) : null
    const caughtAmount = removedShare !== null ? `${removedShare}% of these events` : pluralize(removed ?? 0, 'event')
    return {
        caught:
            removed && !filtersTestAccounts
                ? `Your filter catches ${caughtAmount}, but it's off for this insight.`
                : null,
        missed: check.missed_by_filter
            ? {
                  count: check.distinct_emails ?? check.top_emails.length,
                  noun: 'user',
                  examples: check.top_emails,
                  fallback: "Your team's emails",
                  excludeLabel: check.filter_to_add ? 'Exclude these users' : 'Edit filter',
              }
            : null,
    }
}

function localHostParts(check: InsightDataCheckApi): FilterCheckParts {
    if (!isFinding(check) || !check.filter_to_add) {
        return NOTHING
    }
    return {
        caught: null,
        missed: {
            count: check.distinct_hosts ?? check.top_hosts.length,
            noun: 'host',
            examples: check.top_hosts,
            fallback: 'Localhost events',
            excludeLabel: 'Exclude these hosts',
        },
    }
}

function botTrafficParts(
    check: InsightDataCheckApi,
    filtersTestAccounts: boolean,
    filterRemovesBots: boolean
): FilterCheckParts {
    if (!isFinding(check)) {
        return NOTHING
    }
    if (filterRemovesBots && !filtersTestAccounts) {
        return { caught: "Your filter catches this bot traffic, but it's off for this insight.", missed: null }
    }
    return {
        caught: null,
        missed: {
            count: check.distinct_bots ?? check.top_bots.length,
            noun: 'bot',
            examples: check.top_bots,
            fallback: 'Bot events',
            excludeLabel: 'Exclude these bots',
        },
    }
}

export function filterCheckParts(
    check: InsightDataCheckApi,
    filtersTestAccounts: boolean,
    filterRemovesBots: boolean
): FilterCheckParts {
    switch (check.key) {
        case 'internal_users':
            return internalUsersParts(check, filtersTestAccounts)
        case 'local_development':
            return localHostParts(check)
        case 'bot_traffic':
            return botTrafficParts(check, filtersTestAccounts, filterRemovesBots)
        default:
            return NOTHING
    }
}

function eventNamesOf(events: string[]): string | null {
    return examplesOf(
        events.map((event) => getCoreFilterDefinition(event, TaxonomicFilterGroupType.Events)?.label ?? event),
        null,
        'other event'
    )
}

export function repeatedEventsTextOf(check: InsightDataCheckApi): { found: string; causes: string } {
    const names = eventNamesOf(check.top_events)
    return {
        found: `${names ? `${names} events are` : 'Some events are'} sent twice by the same person, less than 100 ms apart.`,
        causes:
            "This could be because your event is set up twice, you're re-firing an event that's sent automatically, " +
            "or there's a bug in your code. It could even be that PostHog is initialized twice.",
    }
}

// The prompt holds only counts. Event names, hosts and emails come from captured events, which anyone with the
// project token can send, so PostHog AI reads them through its tools instead of as part of the request.
export function postHogAIPromptOf(check: InsightDataCheckApi): string {
    const share = check.share !== null && check.share >= 0.01 ? ` (${Math.round(check.share * 100)}% of them)` : ''
    switch (check.key) {
        case 'duplicate_events':
            return (
                `The data checks on this insight found ${eventCount(check)} events${share} sent twice by the same ` +
                'person less than 100 ms apart. Find which events they are and why, for example the event being set ' +
                'up twice, my code re-firing an event PostHog sends automatically, a bug in my code, or PostHog being ' +
                'initialized twice, and tell me how to fix it.'
            )
        case 'local_development':
            return (
                `The data checks on this insight found ${eventCount(check)} events from local hosts that my project's ` +
                'internal and test users filter keeps. Help me work out whether they come from people building the ' +
                'app, and if they do, change the filter so it removes those hosts.'
            )
        case 'bot_traffic':
            return (
                `The data checks on this insight found ${eventCount(check)} events${share} from bots and crawlers that ` +
                "my project's internal and test users filter keeps. Change the filter so it removes bot and AI agent " +
                'traffic.'
            )
        case 'internal_users':
            return (
                `The data checks on this insight found ${pluralize(check.distinct_emails ?? 0, 'team email')} that my ` +
                "project's internal and test users filter doesn't catch. Change the filter so it removes my team's " +
                'internal and test users without removing real users.'
            )
    }
}

function skippedResult(check: InsightDataCheckApi): string {
    const reason = check.skip_reason ? SKIP_REASONS[check.skip_reason] : null
    return reason ? `Not checked, because ${reason}` : 'Not checked'
}

export function dataCheckText(check: InsightDataCheckApi, filtersTestAccounts: boolean): DataCheckText {
    const name = DATA_CHECK_NAMES[check.key]
    if (check.level === 'skipped') {
        return { name, result: skippedResult(check) }
    }
    if (check.level === 'passed') {
        if (check.key === 'internal_users' && filtersTestAccounts) {
            return { name, result: 'Filtered out' }
        }
        return { name, result: check.events ? `Almost none (${eventCount(check)} events)` : 'None found' }
    }
    const amount =
        check.share !== null && check.share >= 0.01
            ? `${check.scaled ? 'About ' : ''}${Math.round(check.share * 100)}%`
            : capitalizeFirstLetter(eventCount(check))
    return { name, result: `${amount} of these events` }
}
