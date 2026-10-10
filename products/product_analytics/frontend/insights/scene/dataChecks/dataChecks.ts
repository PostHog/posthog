import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { NodeKind } from '~/queries/schema/schema-general'
import type { HogQLQuery, Node } from '~/queries/schema/schema-general'
import { hogql, isEventsNode, isInsightQueryWithSeries } from '~/queries/utils'

export type DataCheckKey = 'internal_users' | 'local_development' | 'bot_traffic' | 'duplicate_events'

/** A pending check is still running. A skipped check did not run, or cannot run for this project. */
export type DataCheckLevel = 'passed' | 'warning' | 'problem' | 'pending' | 'skipped'

export type DataCheckAction = 'filter_internal_users' | 'open_filter_settings'

export interface DataCheck {
    key: DataCheckKey
    level: DataCheckLevel
    /** What the check looks for. It stays the same whatever the check finds. */
    name: string
    result: string
    fix?: string
    action?: DataCheckAction
}

export interface DataCheckCounts {
    events: number
    localEvents: number
    botEvents: number
    /** An estimate, so the count of events sent twice is an estimate too. */
    distinctEvents: number
    /** Events the internal and test users filter removes. Null when the chart applies the filter, or none exists. */
    internalEvents: number | null
}

export interface DataChecksContext {
    filtersInternalUsers: boolean
    hasInternalUsersFilter: boolean
}

export interface DataChecksQueries {
    checks: HogQLQuery
    /** Counts the same events with the internal and test users filter on. Null when that count is not needed. */
    withoutInternalUsers: HogQLQuery | null
}

/** The checks read at most this many days, to bound the cost of a chart with a long date range. */
export const CHECKED_DAYS = 30

const LOCAL_HOST_PATTERN = '(?i)^(localhost|[a-z0-9.-]+\\.localhost|127\\.0\\.0\\.1|0\\.0\\.0\\.0|\\[::1\\])(:[0-9]+)?$'
// An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
const CRAWLER_TRAFFIC_TYPES = ['Bot', 'AI Agent']

// Below these counts and shares a finding is more likely noise than a real problem.
const MIN_FINDING_EVENTS = 50
const MIN_FINDING_SHARE = 0.01
const MIN_DUPLICATE_EVENTS = 100
const MIN_DUPLICATE_SHARE = 0.05
/** From this share of the checked events, a finding is a problem and not a warning. */
const PROBLEM_SHARE = 0.2

const CHECK_NAMES: Record<DataCheckKey, string> = {
    internal_users: 'Internal and test users',
    local_development: 'Local development events',
    bot_traffic: 'Bot and crawler traffic',
    duplicate_events: 'Events sent twice',
}

/** The events a chart reads, 'all' when a series reads every event, or null when the checks cannot cover the chart. */
export function checkedEventNames(source: Node | null | undefined): string[] | 'all' | null {
    if (!source || !isInsightQueryWithSeries(source) || !source.series.length) {
        return null
    }
    const names: (string | null | undefined)[] = []
    for (const node of source.series) {
        // An action or a data warehouse series has no event name to check.
        if (!isEventsNode(node)) {
            return null
        }
        names.push(node.event)
    }
    if (names.some((name) => !name)) {
        return 'all'
    }
    return [...new Set(names as string[])]
}

export function buildDataChecksQueries(
    source: Node | null | undefined,
    { filtersInternalUsers, hasInternalUsersFilter }: DataChecksContext
): DataChecksQueries | null {
    const events = checkedEventNames(source)
    if (!events || !source || !isInsightQueryWithSeries(source)) {
        return null
    }
    const eventCondition = events === 'all' ? hogql.raw('true') : hogql.raw(hogql`event IN ${events}`)
    const where = hogql.raw(
        hogql`{filters} AND timestamp >= now() - INTERVAL ${CHECKED_DAYS} DAY AND ${eventCondition}`
    )
    const filters = {
        dateRange: source.dateRange ?? { date_from: '-7d' },
        properties: convertPropertyGroupToProperties(source.properties),
    }
    const tags = { productKey: 'product_analytics', scene: 'Insight', name: 'insight_data_checks' }
    // The traffic type runs once for each user agent and not for each event, which keeps a chart of every event cheap.
    // One person sending one event from one page twice in one second is one event sent twice.
    const checks = hogql`
        SELECT
            sum(event_count) AS events,
            sum(local_count) AS local_events,
            sumIf(event_count, getTrafficType(user_agent) IN ${CRAWLER_TRAFFIC_TYPES}) AS bot_events,
            sum(distinct_count) AS distinct_events
        FROM (
            SELECT
                toString(properties.$raw_user_agent) AS user_agent,
                count() AS event_count,
                countIf(match(toString(properties.$host), ${LOCAL_HOST_PATTERN})) AS local_count,
                uniq((
                    distinct_id,
                    event,
                    toStartOfSecond(timestamp),
                    toString(properties.$current_url),
                    toString(properties.$screen_name),
                    toString(properties.$feature_flag),
                    elements_chain
                )) AS distinct_count
            FROM events
            WHERE ${where}
            GROUP BY user_agent
        )`
    return {
        checks: {
            kind: NodeKind.HogQLQuery,
            query: checks,
            filters: { ...filters, filterTestAccounts: filtersInternalUsers },
            tags,
        },
        withoutInternalUsers:
            !filtersInternalUsers && hasInternalUsersFilter
                ? {
                      kind: NodeKind.HogQLQuery,
                      query: hogql`SELECT count() AS events FROM events WHERE ${where}`,
                      filters: { ...filters, filterTestAccounts: true },
                      tags,
                  }
                : null,
    }
}

export function dataCheckCountsFromRows(checksRow: unknown, withoutInternalUsersRow: unknown): DataCheckCounts | null {
    if (!Array.isArray(checksRow) || checksRow.length < 4) {
        return null
    }
    const [events, localEvents, botEvents, distinctEvents] = checksRow.map((value) => Number(value) || 0)
    const withoutInternalUsers = Array.isArray(withoutInternalUsersRow) ? Number(withoutInternalUsersRow[0]) || 0 : null
    return {
        events,
        localEvents,
        botEvents,
        distinctEvents,
        internalEvents: withoutInternalUsers === null ? null : Math.max(events - withoutInternalUsers, 0),
    }
}

function findingLevel(share: number): DataCheckLevel {
    return share >= PROBLEM_SHARE ? 'problem' : 'warning'
}

function isFinding(count: number, share: number): boolean {
    return count >= MIN_FINDING_EVENTS && share >= MIN_FINDING_SHARE
}

function passedResult(count: number): string {
    return count ? `Almost none found (${humanFriendlyNumber(count)} events)` : 'None found'
}

function internalUsersCheck(
    { events, internalEvents }: DataCheckCounts,
    { filtersInternalUsers, hasInternalUsersFilter }: DataChecksContext
): DataCheck {
    const key = 'internal_users'
    const name = CHECK_NAMES[key]
    if (filtersInternalUsers) {
        return { key, level: 'passed', name, result: 'Filtered out of this chart' }
    }
    if (!hasInternalUsersFilter || internalEvents === null) {
        return {
            key,
            level: 'skipped',
            name,
            result: "Can't check yet, because this project has no internal and test users filter",
            fix: 'Set up the filter so PostHog knows which users are your own team.',
            action: 'open_filter_settings',
        }
    }
    const share = internalEvents / events
    if (!isFinding(internalEvents, share)) {
        return { key, level: 'passed', name, result: passedResult(internalEvents) }
    }
    return {
        key,
        level: findingLevel(share),
        name,
        result: `${percentage(share, 0)} of these events came from internal and test users`,
        fix: 'Turn on the internal and test users filter for this insight.',
        action: 'filter_internal_users',
    }
}

function localDevelopmentCheck({ events, localEvents }: DataCheckCounts): DataCheck {
    const key = 'local_development'
    const name = CHECK_NAMES[key]
    const share = localEvents / events
    // No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    if (localEvents < MIN_FINDING_EVENTS) {
        return { key, level: 'passed', name, result: passedResult(localEvents) }
    }
    return {
        key,
        level: findingLevel(share),
        name,
        result:
            share >= MIN_FINDING_SHARE
                ? `${percentage(share, 0)} of these events came from local development`
                : `${humanFriendlyNumber(localEvents)} of these events came from local development`,
        fix: 'Send local traffic to a separate project, or exclude localhost in the internal and test users filter and turn that filter on for this insight.',
        action: 'open_filter_settings',
    }
}

function botTrafficCheck({ events, botEvents }: DataCheckCounts): DataCheck {
    const key = 'bot_traffic'
    const name = CHECK_NAMES[key]
    const share = botEvents / events
    if (!isFinding(botEvents, share)) {
        return { key, level: 'passed', name, result: passedResult(botEvents) }
    }
    return {
        key,
        level: findingLevel(share),
        name,
        result: `${percentage(share, 0)} of these events came from bots and crawlers`,
        fix: 'In the internal and test users filter, add "Traffic type is not Bot or AI Agent", and turn that filter on for this insight.',
        action: 'open_filter_settings',
    }
}

function duplicateEventsCheck({ events, distinctEvents }: DataCheckCounts): DataCheck {
    const key = 'duplicate_events'
    const name = CHECK_NAMES[key]
    const duplicates = Math.max(events - distinctEvents, 0)
    const share = duplicates / events
    if (duplicates < MIN_DUPLICATE_EVENTS || share < MIN_DUPLICATE_SHARE) {
        // The count is an estimate, so a small one can be an error of the estimate and not a real event.
        return {
            key,
            level: 'passed',
            name,
            result: share < MIN_FINDING_SHARE ? 'None found' : `Few found (about ${percentage(share, 0)})`,
        }
    }
    return {
        key,
        level: findingLevel(share),
        name,
        result: `About ${percentage(share, 0)} of these events were sent twice within one second`,
        fix: 'Start PostHog once in your app, and send each event from one place only.',
    }
}

/** Every check with the same level and result, for a run that is still going or that produced nothing to read. */
export function unevaluatedDataChecks(level: 'pending' | 'skipped', result: string): DataCheck[] {
    return (Object.keys(CHECK_NAMES) as DataCheckKey[]).map((key) => ({ key, level, name: CHECK_NAMES[key], result }))
}

/** Every check, in a fixed order, so the list shows what was checked whatever the result. */
export function evaluateDataChecks(counts: DataCheckCounts, context: DataChecksContext): DataCheck[] {
    if (!counts.events) {
        return unevaluatedDataChecks('skipped', `No events in the last ${CHECKED_DAYS} days to check`)
    }
    return [
        internalUsersCheck(counts, context),
        localDevelopmentCheck(counts),
        botTrafficCheck(counts),
        duplicateEventsCheck(counts),
    ]
}
