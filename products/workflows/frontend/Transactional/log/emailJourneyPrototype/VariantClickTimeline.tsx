// PROTOTYPE (ticket #385), throwaway. Variant A, round 2: today's delivery header on top, then each click with the
// session it started, inline, and a link to every event behind it. The email sits below, as on today's page. The
// side column holds the person and this email's numbers across all its sends.
import { useState } from 'react'

import { IconCursorClick, IconExternal, IconLetter } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { TransactionalEmailDeliveryProgress } from '../TransactionalEmailDeliveryProgress'
import { impactData } from './impactFixtures'
import { EVENTS_OFF_TEXT, NO_CLICKS_TEXT, NO_PERSON_TEXT, NOT_TRACKED_TEXT, noSessionText } from './journeyCopy'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { JourneyData, JourneySession, linkFor, sessionsFromClicks } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'
import { JourneySessionSummary } from './JourneySessionSummary'
import { journeyUrl } from './useEmailJourneyPrototype'
import { asDetail } from './VariantToday'

/** Opens the event behind a step. Hidden when engagement events are off, since there is no event to open. */
export function EventLink({
    data,
    id,
    at,
    event,
}: {
    data: JourneyData
    id: string
    at: string
    event: string
}): JSX.Element | null {
    if (!data.engagementEventsOn && event.startsWith('$workflows_email_')) {
        return null
    }
    return (
        <Link to={urls.event(`proto-${id}`, at, event)} className="text-xs" data-attr="prototype-journey-event-link">
            View event
        </Link>
    )
}

export function VariantClickTimeline({ data }: { data: JourneyData }): JSX.Element {
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const clicks = data.clicks
    const sessions = sessionsFromClicks(data)
    const across = impactData('full')

    return (
        <div className="@container flex flex-col gap-4">
            <TransactionalEmailDeliveryProgress email={asDetail(data)} />
            <div className="flex flex-col @3xl:flex-row gap-4 items-start">
                <div className="w-full @3xl:flex-1 min-w-0 flex flex-col gap-4">
                    <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                        <div className="flex flex-col gap-0.5">
                            <h3 className="text-base font-semibold m-0">What this email led to</h3>
                            <p className="text-xs text-secondary m-0">
                                {clicks && clicks.length
                                    ? `${pluralize(clicks.length, 'click')}, ${pluralize(sessions, 'session')} in your product`
                                    : 'Each link click and the session it started in your product.'}
                            </p>
                        </div>
                        {!data.engagementEventsOn && <LemonBanner type="info">{EVENTS_OFF_TEXT}</LemonBanner>}
                        {clicks === null ? (
                            <p className="text-sm text-secondary m-0">{NOT_TRACKED_TEXT}</p>
                        ) : clicks.length === 0 ? (
                            <p className="text-sm text-secondary m-0">{NO_CLICKS_TEXT}</p>
                        ) : (
                            <ol className="m-0 p-0 list-none flex flex-col">
                                <li className="flex gap-3 pb-4">
                                    <span className="flex flex-col items-center">
                                        <IconLetter className="text-lg text-secondary" />
                                        <span className="w-px flex-1 bg-border mt-1" />
                                    </span>
                                    <span className="text-sm text-secondary flex flex-wrap items-center gap-x-2">
                                        <span>
                                            Delivered{' '}
                                            <TZLabel time={data.deliveredAt} formatDate="MMM D" formatTime="HH:mm" />
                                        </span>
                                        <EventLink
                                            data={data}
                                            id="delivered"
                                            at={data.deliveredAt}
                                            event="$workflows_email_delivered"
                                        />
                                        {data.openedAt && (
                                            <>
                                                <span>
                                                    · Opened{' '}
                                                    <TZLabel
                                                        time={data.openedAt}
                                                        formatDate="MMM D"
                                                        formatTime="HH:mm"
                                                    />
                                                </span>
                                                <EventLink
                                                    data={data}
                                                    id="opened"
                                                    at={data.openedAt}
                                                    event="$workflows_email_opened"
                                                />
                                            </>
                                        )}
                                    </span>
                                </li>
                                {clicks.map((click, index) => {
                                    const link = linkFor(data, click.linkKey)
                                    return (
                                        <li key={click.id} className="flex gap-3 pb-4">
                                            <span className="flex flex-col items-center">
                                                <IconCursorClick className="text-lg" />
                                                {index < clicks.length - 1 && (
                                                    <span className="w-px flex-1 bg-border mt-1" />
                                                )}
                                            </span>
                                            <div className="flex-1 min-w-0 flex flex-col gap-2">
                                                <div className="flex flex-wrap items-center gap-x-2 text-sm">
                                                    <span>
                                                        Clicked <strong>{link.label}</strong>
                                                    </span>
                                                    <span className="text-secondary">
                                                        <TZLabel
                                                            time={click.at}
                                                            formatDate="MMM D"
                                                            formatTime="HH:mm"
                                                        />
                                                    </span>
                                                    <span className="text-xs text-secondary truncate flex items-center gap-1">
                                                        <IconExternal /> {link.url.replace('https://', '')}
                                                    </span>
                                                    <EventLink
                                                        data={data}
                                                        id={click.id}
                                                        at={click.at}
                                                        event="$workflows_email_link_clicked"
                                                    />
                                                </div>
                                                <div className="border rounded p-3 bg-surface-secondary">
                                                    {click.session ? (
                                                        <JourneySessionSummary
                                                            session={click.session}
                                                            data={data}
                                                            onWatch={setWatching}
                                                        />
                                                    ) : (
                                                        <div className="flex flex-col gap-1">
                                                            <LemonTag type="muted" className="self-start">
                                                                No session found
                                                            </LemonTag>
                                                            <span className="text-xs text-secondary">
                                                                {noSessionText(click, link, data)}
                                                            </span>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </li>
                                    )
                                })}
                            </ol>
                        )}
                    </section>
                    <JourneyEmailPreview data={data} />
                </div>
                <div className="w-full @3xl:w-96 @6xl:w-[28rem] shrink-0 flex flex-col gap-4">
                    <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                        <h3 className="text-sm font-semibold m-0">Recipient</h3>
                        {data.person ? (
                            <>
                                <span className="text-sm">
                                    {data.person.name} · <span className="text-secondary">{data.person.email}</span>
                                </span>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    className="self-start"
                                    to={urls.personByDistinctId(data.person.distinctId)}
                                >
                                    View person
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <span className="text-sm">{data.recipient}</span>
                                <span className="text-xs text-secondary">{NO_PERSON_TEXT}</span>
                            </>
                        )}
                    </section>
                    <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                        <h3 className="text-sm font-semibold m-0">"{data.emailName}" across all its sends</h3>
                        <span className="text-sm">
                            {across.clicked!.toLocaleString()} people clicked, {across.converted!.toLocaleString()} did
                            "{across.goal!.event}" in the {across.period.toLowerCase()}.
                        </span>
                        <span className="text-xs text-secondary">
                            Most common problem: {across.scanner!.findings[0].title.toLowerCase()}.
                        </span>
                        <LemonButton type="secondary" size="small" className="self-start" to={journeyUrl('D')}>
                            See this email's impact
                        </LemonButton>
                    </section>
                </div>
            </div>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
