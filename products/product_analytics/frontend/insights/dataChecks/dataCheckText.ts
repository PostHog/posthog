import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { capitalizeFirstLetter, humanList, pluralize } from 'lib/utils/strings'

import { getFilterLabel } from '~/taxonomy/helpers'

import type {
    InsightDataCheckApi,
    InsightDataCheckKeyEnumApi,
    InsightDataCheckSkipReasonEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { REPEAT_WINDOW_MILLISECONDS } from './repeatedEventsQuery'

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
    filtered_by_traffic_type: "this insight's filters already choose which traffic types to keep",
    hidden_property: 'a property it reads is hidden from you',
    invalid_filter: "the project's internal and test users filter cannot run",
    on_request: 'it would read a lot of data, so it runs only in a full check',
}

function eventCount(check: InsightDataCheckApi): string {
    const count = humanFriendlyNumber(check.events ?? 0)
    return check.scaled ? `about ${count}` : count
}

// Below 1% a share rounds to 0%, so the text gives a count instead.
function percentOf(share: number | null): string | null {
    return share !== null && share >= 0.01 ? percentage(share, 0) : null
}

function shareOf(check: InsightDataCheckApi, part: number): string | null {
    return percentOf(check.share !== null && check.events ? (check.share * part) / check.events : null)
}

export interface FilterCheckParts {
    /** Set when the project's filter catches these events but the insight leaves the filter off. */
    caught: string | null
    missed: {
        count: number
        noun: string
        examples: string[]
        fallback: string
        predicate: string
        explanation: string | null
    } | null
}

const NOTHING: FilterCheckParts = { caught: null, missed: null }

export function isFinding(check: InsightDataCheckApi): boolean {
    return check.level === 'warning' || check.level === 'problem'
}

function notCaught(count: number): string {
    return `${count === 1 ? "isn't" : "aren't"} caught by your internal and test users filter.`
}

function missedUserCount(check: InsightDataCheckApi): number {
    return check.distinct_emails ?? check.top_emails.length
}

function internalUsersParts(check: InsightDataCheckApi, filtersTestAccounts: boolean): FilterCheckParts {
    const removed = check.removed_by_filter
    const removedPercent = removed ? shareOf(check, removed) : null
    const caughtAmount = removedPercent ? `${removedPercent} of these events` : pluralize(removed ?? 0, 'event')
    const count = missedUserCount(check)
    return {
        caught:
            removed && !filtersTestAccounts
                ? `Your filter catches ${caughtAmount}, but it's off for this insight.`
                : null,
        missed: check.missed_by_filter
            ? {
                  count,
                  noun: 'user',
                  examples: check.top_emails,
                  fallback: 'Some users',
                  predicate: `${count === 1 ? 'has an email that matches' : 'have emails that match'} your team, but none of your filter's rules remove them.`,
                  explanation:
                      "An email matches your team when it's on the same domain as someone in your organization, " +
                      'or looks like a test account, such as test@ or name+qa@.',
              }
            : null,
    }
}

function localHostParts(check: InsightDataCheckApi): FilterCheckParts {
    if (!isFinding(check) || !check.filter_to_add) {
        return NOTHING
    }
    const count = check.distinct_hosts ?? check.top_hosts.length
    return {
        caught: null,
        missed: {
            count,
            noun: 'host',
            examples: check.top_hosts,
            fallback: 'Localhost events',
            predicate: notCaught(count),
            explanation: null,
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
    const count = check.distinct_bots ?? check.top_bots.length
    return {
        caught: null,
        missed: {
            count,
            noun: 'bot',
            examples: check.top_bots,
            fallback: 'Bot events',
            predicate: notCaught(count),
            explanation: null,
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

export function repeatedEventsTextOf(check: InsightDataCheckApi): { found: string; causes: string } {
    const names = humanList(check.top_events.map((event) => getFilterLabel(event, TaxonomicFilterGroupType.Events)))
    return {
        found: `${names ? `${names} events are` : 'Some events are'} sent twice by the same person, less than ${REPEAT_WINDOW_MILLISECONDS} ms apart.`,
        causes:
            "This could be because your event is set up twice, you're re-firing an event that's sent automatically, " +
            "or there's a bug in your code. It could even be that PostHog is initialized twice.",
    }
}

// The prompt holds only counts. Event names, hosts and emails come from captured events, which anyone with the
// project token can send, so PostHog AI reads them through its tools instead of as part of the request.
export function postHogAIPromptOf(check: InsightDataCheckApi): string {
    const percent = percentOf(check.share)
    const share = percent ? ` (${percent} of them)` : ''
    switch (check.key) {
        case 'duplicate_events':
            return (
                `The data checks on this insight found ${eventCount(check)} events${share} sent twice by the same ` +
                `person less than ${REPEAT_WINDOW_MILLISECONDS} ms apart. Find which events they are and why, for example the event being set ` +
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

// The server skips the bot check whenever the insight's filters read traffic type, and cannot tell when the rule
// comes from the project's filter.
export function botsFilteredOut(
    check: InsightDataCheckApi,
    filtersTestAccounts: boolean,
    filterRemovesBots: boolean
): boolean {
    return check.skip_reason === 'filtered_by_traffic_type' && filtersTestAccounts && filterRemovesBots
}

export function dataCheckText(
    check: InsightDataCheckApi,
    filtersTestAccounts: boolean,
    filterRemovesBots: boolean
): DataCheckText {
    const name = DATA_CHECK_NAMES[check.key]
    if (botsFilteredOut(check, filtersTestAccounts, filterRemovesBots)) {
        return { name, result: 'Filtered out' }
    }
    if (check.level === 'skipped') {
        return { name, result: skippedResult(check) }
    }
    if (check.level === 'passed') {
        if (check.key === 'internal_users' && filtersTestAccounts) {
            if (!check.missed_by_filter) {
                return { name, result: 'Filtered out' }
            }
            const missed = missedUserCount(check)
            return { name, result: `Filtered out, except ${missed ? pluralize(missed, 'user') : 'some users'}` }
        }
        return { name, result: check.events ? `Almost none (${eventCount(check)} events)` : 'None found' }
    }
    const percent = percentOf(check.share)
    const amount = percent ? `${check.scaled ? 'About ' : ''}${percent}` : capitalizeFirstLetter(eventCount(check))
    return { name, result: `${amount} of these events` }
}
