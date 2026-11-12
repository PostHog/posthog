import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { hogql } from 'lib/utils/hogql'

import {
    transactionalEmailLogActivityRetrieve,
    transactionalEmailLogList,
} from 'products/messaging/frontend/generated/api'
import type {
    TransactionalEmailActivityEventApi,
    TransactionalEmailLogEntryApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { ACTIVITY_WINDOW_DAYS, ActivityEvent, ActivityPerson, PersonActivity } from './emailActivity'
import { LOG_RETENTION_DAYS } from './transactionalEmailLogLogic'

const OTHER_EMAILS_LIMIT = 20

const QUERY_TAGS = { productKey: 'workflows', scene: 'TransactionalEmailLogEntry' }

function toEvent(event: TransactionalEmailActivityEventApi): ActivityEvent {
    return {
        uuid: event.uuid,
        event: event.event,
        timestamp: event.timestamp,
        url: event.current_url,
        pathname: event.pathname,
        sessionId: event.session_id,
        eventType: event.event_type,
        elementsChain: event.elements_chain,
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

export async function fetchPersonActivity(projectId: number, messageId: string): Promise<PersonActivity> {
    const activity = await transactionalEmailLogActivityRetrieve(String(projectId), messageId)
    return {
        before: activity.before.map(toEvent),
        after: activity.after.map(toEvent),
        hasMoreBefore: activity.has_more_before,
        hasMoreAfter: activity.has_more_after,
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
