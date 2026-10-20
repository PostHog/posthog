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

export const TRAFFIC_TYPE_PROPERTY = '$virt_traffic_type'

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

export function filterCheckParts(
    check: InsightDataCheckApi,
    filtersTestAccounts: boolean,
    filterRemovesBots: boolean
): FilterCheckParts {
    const found = check.level === 'warning' || check.level === 'problem'
    switch (check.key) {
        case 'internal_users': {
            const removed = check.removed_by_filter
            const removedShare = removed ? shareOf(check, removed) : null
            return {
                caught:
                    removed && !filtersTestAccounts
                        ? `Your filter catches ${removedShare !== null ? `${removedShare}% of these events` : pluralize(removed, 'event')}, but it's off for this insight.`
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
        case 'local_development':
            return {
                caught: null,
                missed:
                    found && check.filter_to_add
                        ? {
                              count: check.distinct_hosts ?? check.top_hosts.length,
                              noun: 'host',
                              examples: check.top_hosts,
                              fallback: 'Localhost events',
                              excludeLabel: 'Exclude these hosts',
                          }
                        : null,
            }
        case 'bot_traffic':
            if (!found) {
                return { caught: null, missed: null }
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
        default:
            return { caught: null, missed: null }
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

export function postHogAIPromptOf(check: InsightDataCheckApi): string {
    if (check.key === 'duplicate_events') {
        const share = check.share !== null ? ` (${Math.round(check.share * 100)}% of them)` : ''
        const events = check.top_events.length ? `, mostly ${check.top_events.join(', ')}` : ''
        return (
            `The data checks on my insight found ${eventCount(check)} events${share} sent twice by the same person ` +
            `less than 100 ms apart${events}. Find out why, for example the event being set up twice, my code re-firing ` +
            'an event PostHog sends automatically, a bug in my code, or PostHog being initialized twice, and tell me ' +
            'how to fix it.'
        )
    }
    if (check.key === 'local_development') {
        const hosts = examplesOf(check.top_hosts, check.distinct_hosts, 'other host') ?? 'localhost'
        return (
            `The data checks on my insight found ${humanFriendlyNumber(check.events ?? 0)} events from ${hosts} ` +
            "that my project's internal and test users filter keeps. Help me work out whether they come from " +
            'people building the app, and if they do, change the filter so it removes every localhost host.'
        )
    }
    if (check.key === 'bot_traffic') {
        const bots = examplesOf(check.top_bots, check.distinct_bots, 'other bot') ?? 'bots and crawlers'
        return (
            `The data checks on my insight found ${eventCount(check)} events from ${bots} that my project's ` +
            'internal and test users filter keeps. Change the filter so it removes bot and AI agent traffic.'
        )
    }
    const emails = examplesOf(check.top_emails, check.distinct_emails, 'other') ?? "my team's emails"
    return (
        `The data checks on my insight found that ${emails} aren't caught by my project's internal and test ` +
        "users filter. Change the filter so it removes my team's internal and test users without removing real users."
    )
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
