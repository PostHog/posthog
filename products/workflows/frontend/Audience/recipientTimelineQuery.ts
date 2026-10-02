import { HogQLQueryString, hogql } from '~/queries/utils'

export const RECIPIENT_TIMELINE_DAYS = 30
export const RECIPIENT_TIMELINE_LIMIT = 100

export type RecipientTimelineRow = [
    event: string,
    timestamp: string,
    subject: string | null,
    linkUrl: string | null,
    topicId: string | null,
]

export interface RecipientTimelineEvent {
    event: string
    timestamp: string
    subject: string | null
    linkUrl: string | null
    topicId: string | null
}

/**
 * Email events for one address. Unsubscribes carry the address as `$email` and have no `$email_to`,
 * so they match on that instead. Neither side matches on a person.
 */
export function recipientTimelineQuery(email: string): HogQLQueryString {
    const address = email.trim().toLowerCase()
    return hogql`
        SELECT event, timestamp, properties.$email_subject, properties.$link_url, properties.category
        FROM events
        WHERE timestamp >= now() - toIntervalDay(${RECIPIENT_TIMELINE_DAYS})
            AND startsWith(event, '$workflows_email_')
            AND (
                lower(properties.$email_to) = ${address}
                OR (event = '$workflows_email_unsubscribed' AND lower(properties.$email) = ${address})
            )
        ORDER BY timestamp DESC
        LIMIT ${RECIPIENT_TIMELINE_LIMIT}`
}

export function toRecipientTimelineEvent([
    event,
    timestamp,
    subject,
    linkUrl,
    topicId,
]: RecipientTimelineRow): RecipientTimelineEvent {
    return { event, timestamp, subject, linkUrl, topicId }
}
