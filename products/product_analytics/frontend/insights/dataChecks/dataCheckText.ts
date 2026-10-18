import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type {
    InsightDataCheckApi,
    InsightDataCheckKeyEnumApi,
    InsightDataCheckSkipReasonEnumApi,
} from 'products/product_analytics/frontend/generated/api.schemas'

export interface DataCheckText {
    name: string
    result: string
    /** What to change. Null when the check found nothing to fix. */
    fix: string | null
}

export const DATA_CHECK_NAMES: Record<InsightDataCheckKeyEnumApi, string> = {
    internal_users: 'Internal and test users',
    local_development: 'Local development events',
    bot_traffic: 'Bot and crawler traffic',
    duplicate_events: 'Events sent twice',
}

// What the check looks for, as it reads after "No".
const LOOKS_FOR: Record<InsightDataCheckKeyEnumApi, string> = {
    internal_users: 'internal or test users',
    local_development: 'local development events',
    bot_traffic: 'bots or crawlers',
    duplicate_events: 'events sent twice',
}

const FOUND: Record<InsightDataCheckKeyEnumApi, string> = {
    internal_users: 'of these events came from internal and test users',
    local_development: 'of these events came from local development',
    bot_traffic: 'of these events came from bots and crawlers',
    duplicate_events: 'of these events were sent twice within one second',
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

function inTheFilter(change: string, filtersTestAccounts: boolean): string {
    return filtersTestAccounts ? `${change}.` : `${change}, and turn that filter on for this insight.`
}

function fixOf(check: InsightDataCheckApi, filtersTestAccounts: boolean): string {
    switch (check.key) {
        case 'internal_users':
            if (check.action === 'filter_internal_users') {
                return 'Turn on the internal and test users filter for this insight.'
            }
            return inTheFilter(
                "Change the internal and test users filter so that it removes your team's emails",
                filtersTestAccounts
            )
        case 'local_development':
            return inTheFilter(
                'Send local traffic to a separate project, or exclude localhost in the internal and test users filter',
                filtersTestAccounts
            )
        case 'bot_traffic':
            return inTheFilter(
                'In the internal and test users filter, add "Traffic type is not Bot or AI Agent"',
                filtersTestAccounts
            )
        case 'duplicate_events':
            return 'Start PostHog once in your app, and send each event from one place only.'
    }
}

/** The words for one check's result, from the fields the server returns. */
export function dataCheckText(check: InsightDataCheckApi, filtersTestAccounts: boolean): DataCheckText {
    const name = DATA_CHECK_NAMES[check.key]
    if (check.level === 'skipped') {
        const reason = check.skip_reason ? SKIP_REASONS[check.skip_reason] : null
        return { name, result: reason ? `Not checked, because ${reason}` : 'Not checked', fix: null }
    }
    if (check.level === 'passed') {
        if (check.key === 'internal_users' && filtersTestAccounts) {
            return { name, result: 'Internal and test users are filtered out', fix: null }
        }
        const result = check.events
            ? `Almost no ${LOOKS_FOR[check.key]} found (${eventCount(check)} events)`
            : `No ${LOOKS_FOR[check.key]} found`
        return { name, result, fix: null }
    }
    const amount =
        check.share !== null && check.share >= 0.01
            ? `${check.scaled ? 'About ' : ''}${Math.round(check.share * 100)}%`
            : capitalizeFirstLetter(eventCount(check))
    return { name, result: `${amount} ${FOUND[check.key]}`, fix: fixOf(check, filtersTestAccounts) }
}
