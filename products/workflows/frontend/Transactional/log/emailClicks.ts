import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'

import type {
    EmailClickNoSessionReasonEnumApi,
    TransactionalEmailClickApi,
    TransactionalEmailClickSessionApi,
    TransactionalEmailLogDetailApi,
    TransactionalEmailOwnEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

export type EmailOutcomeRow =
    | { kind: 'delivered' | 'opened'; key: string; at: string; eventUuid: string | null }
    | {
          kind: 'click'
          key: string
          at: string
          eventUuid: string | null
          link: string | null
          session: TransactionalEmailClickSessionApi | null
          noSessionReason: EmailClickNoSessionReasonEnumApi | null
      }

export const NO_SESSION_REASON: Record<EmailClickNoSessionReasonEnumApi, string> = {
    off_site: "The link goes to another site, so the visit isn't in PostHog.",
    sensitive: "This email is marked sensitive, so its links can't be followed to a visit.",
    link_tagging_off: "Link tagging is off for this project, so visits can't be tied to clicks.",
    link_unknown: "The link wasn't recorded, so its visit can't be found.",
    not_found: 'No visit from this click was found.',
}

const OWN_EVENT: Record<'delivered' | 'opened', string> = {
    delivered: '$workflows_email_delivered',
    opened: '$workflows_email_opened',
}

/** Clicks and visits come from events, so a send that went out has them even when no copy of the email was kept. */
export function emailWentOut(email: TransactionalEmailLogDetailApi): boolean {
    return email.timeline.some((step) => step.kind === 'sent')
}

/** When the email was delivered and first opened, then each click with the session it started, oldest first. */
export function emailOutcomeRows(
    email: TransactionalEmailLogDetailApi,
    clicks: TransactionalEmailClickApi[],
    emailEvents: TransactionalEmailOwnEventApi[]
): EmailOutcomeRow[] {
    const rows: EmailOutcomeRow[] = []
    for (const kind of ['delivered', 'opened'] as const) {
        const step = email.timeline.find((event) => event.kind === kind)
        if (step) {
            const event = emailEvents.find((own) => own.event === OWN_EVENT[kind])
            rows.push({ kind, key: kind, at: step.at, eventUuid: event?.uuid ?? null })
        }
    }
    clicks.forEach((click, index) =>
        rows.push({
            kind: 'click',
            key: `click-${index}`,
            at: click.at,
            eventUuid: click.event_uuid,
            link: click.link_url,
            session: click.session,
            noSessionReason: click.no_session_reason,
        })
    )
    return rows
}

/** The link without its scheme, such as `app.example.com/billing`. */
export function linkLabel(link: string): string {
    try {
        const url = new URL(link)
        const path = url.pathname === '/' ? '' : url.pathname
        return `${url.host}${path}${url.search}`
    } catch {
        return link
    }
}

/** What the session looked like, such as "Desktop · Chrome · Berlin · 4m 10s · 3 pages". */
export function sessionSummary(session: TransactionalEmailClickSessionApi): string {
    return [
        session.device_type,
        session.browser,
        session.city,
        session.duration_seconds !== null ? humanFriendlyDuration(session.duration_seconds) : null,
        session.pageview_count !== null ? pluralize(session.pageview_count, 'page') : null,
    ]
        .filter(Boolean)
        .join(' · ')
}

/** The page the click landed on, without the run tag the link carried. */
export function landingPath(session: TransactionalEmailClickSessionApi): string {
    try {
        const url = new URL(session.landing_url)
        url.searchParams.delete('ph_workflow_run')
        return `${url.pathname}${url.search}`
    } catch {
        return session.landing_url
    }
}
