import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { hogql } from 'lib/utils/hogql'

import { transactionalEmailLogList } from 'products/messaging/frontend/generated/api'
import type { TransactionalEmailLogEntryApi } from 'products/messaging/frontend/generated/api.schemas'

import {
    ACTIVITY_AFTER_LIMIT,
    ACTIVITY_BEFORE_LIMIT,
    ACTIVITY_WINDOW_DAYS,
    ActivityEvent,
    ActivityPerson,
    PersonActivity,
} from './emailActivity'
import { LOG_RETENTION_DAYS } from './transactionalEmailLogLogic'

const OTHER_EMAILS_LIMIT = 20

// Events that describe the SDK rather than something the person did.
const HIDDEN_EVENTS = [
    '$feature_flag_called',
    '$identify',
    '$set',
    '$groupidentify',
    '$create_alias',
    '$pageleave',
    '$web_vitals',
    '$opt_in',
    '$autocapture_disabled',
    '$dead_click',
    '$exception',
    '$feature_view',
    '$feature_interaction',
    '$snapshot',
]

const QUERY_TAGS = { productKey: 'workflows', scene: 'TransactionalEmailLogEntry' }

function toEvent(row: any[]): ActivityEvent {
    const [uuid, event, timestamp, url, pathname, sessionId, eventType, elementsChain] = row
    return {
        uuid,
        event,
        timestamp,
        url: url || null,
        pathname: pathname || null,
        sessionId: sessionId || null,
        eventType: eventType || null,
        elementsChain: elementsChain || '',
    }
}

export async function fetchActivityPerson(distinctId: string): Promise<ActivityPerson | null> {
    const response = await api.queryHogQL(
        hogql`SELECT id, properties, created_at
FROM persons
WHERE id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id = ${distinctId})
LIMIT 1`,
        QUERY_TAGS
    )
    const row = response.results?.[0]
    if (!row) {
        return null
    }
    const [id, properties, createdAt] = row
    return {
        id,
        properties: typeof properties === 'string' ? JSON.parse(properties) : (properties ?? {}),
        createdAt,
    }
}

export async function fetchPersonActivity(personId: string, sentAt: string): Promise<PersonActivity> {
    const sent = dayjs(sentAt)
    const from = sent.subtract(ACTIVITY_WINDOW_DAYS, 'day')
    const to = sent.add(ACTIVITY_WINDOW_DAYS, 'day')
    const columns = hogql`uuid, event, timestamp, properties.$current_url, properties.$pathname, properties.$session_id, properties.$event_type, elements_chain`
    const [before, after] = await Promise.all([
        api.queryHogQL(
            hogql`SELECT ${hogql.raw(columns)} FROM events
WHERE person_id = ${personId} AND timestamp >= ${from} AND timestamp < ${sent}
AND event NOT IN ${HIDDEN_EVENTS}
ORDER BY timestamp DESC
LIMIT ${ACTIVITY_BEFORE_LIMIT + 1}`,
            QUERY_TAGS
        ),
        api.queryHogQL(
            hogql`SELECT ${hogql.raw(columns)} FROM events
WHERE person_id = ${personId} AND timestamp >= ${sent} AND timestamp <= ${to}
AND event NOT IN ${HIDDEN_EVENTS}
ORDER BY timestamp ASC
LIMIT ${ACTIVITY_AFTER_LIMIT + 1}`,
            QUERY_TAGS
        ),
    ])
    const beforeRows = (before.results ?? []).map(toEvent)
    const afterRows = (after.results ?? []).map(toEvent)
    return {
        before: beforeRows.slice(0, ACTIVITY_BEFORE_LIMIT).reverse(),
        after: afterRows.slice(0, ACTIVITY_AFTER_LIMIT),
        hasMoreBefore: beforeRows.length > ACTIVITY_BEFORE_LIMIT,
        hasMoreAfter: afterRows.length > ACTIVITY_AFTER_LIMIT,
    }
}

/** Other emails the same recipient got in the activity window, newest last. */
export async function fetchOtherEmails(
    projectId: number,
    recipient: string,
    messageId: string,
    sentAt: string
): Promise<TransactionalEmailLogEntryApi[]> {
    const sent = dayjs(sentAt)
    const now = dayjs()
    const oldest = now.subtract(LOG_RETENTION_DAYS, 'day')
    const from = sent.subtract(ACTIVITY_WINDOW_DAYS, 'day')
    const to = sent.add(ACTIVITY_WINDOW_DAYS, 'day')
    const response = await transactionalEmailLogList(String(projectId), {
        search: recipient,
        date_from: (from.isBefore(oldest) ? oldest : from).toISOString(),
        date_to: (to.isAfter(now) ? now : to).toISOString(),
        limit: OTHER_EMAILS_LIMIT,
    })
    // Search matches part of an address, so keep only this recipient's own sends.
    return response.results
        .filter((entry) => entry.message_id !== messageId && entry.recipient.toLowerCase() === recipient.toLowerCase())
        .sort((a, b) => dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf())
}
