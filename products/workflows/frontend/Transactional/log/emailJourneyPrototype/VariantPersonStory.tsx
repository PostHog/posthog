// PROTOTYPE (ticket #385), throwaway. Variant B: the page leads with the person and what they did after the email.
// One table holds every session in the week after the send, and says which ones a click from this email started.
import { useState } from 'react'

import { IconPlayFilled } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import {
    EVENTS_OFF_TEXT,
    NO_CLICKS_TEXT,
    NO_PERSON_TEXT,
    NOT_TRACKED_TEXT,
    noSessionText,
    whoText,
} from './journeyCopy'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { JourneyClick, JourneyData, JourneySession, linkFor } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'

interface SessionRow {
    session: JourneySession
    click: JourneyClick | null
}

function summary(data: JourneyData): string {
    const name = data.person?.name.split(' ')[0] ?? 'The recipient'
    if (data.clicks === null) {
        return `${name} got this email. Clicks aren't tracked, so no session can be tied to it.`
    }
    if (!data.clicks.length) {
        return `${name} opened this email but hasn't clicked a link yet.`
    }
    const fromClicks = data.clicks.filter((click) => click.session)
    const firstOutcome = fromClicks
        .flatMap((click) => click.session!.events.filter((e) => e.outcome).map((e) => ({ e, click })))
        .at(0)
    const parts = [
        `${name} clicked ${pluralize(data.clicks.length, 'time')}`,
        fromClicks.length
            ? `came back in ${pluralize(fromClicks.length, 'session')} from this email`
            : 'but no session came from those clicks',
    ]
    const outcome = firstOutcome
        ? `, and did “${firstOutcome.e.label}” ${humanFriendlyDuration(
              dayjs(firstOutcome.e.at).diff(dayjs(firstOutcome.click.at), 'second'),
              { maxUnits: 1 }
          )} after clicking.`
        : '.'
    return parts.join(', ') + outcome
}

export function VariantPersonStory({ data }: { data: JourneyData }): JSX.Element {
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const [showEmail, setShowEmail] = useState(false)

    const rows: SessionRow[] = [
        ...(data.clicks ?? []).filter((click) => click.session).map((click) => ({ session: click.session!, click })),
        ...data.otherSessions.map((session) => ({ session, click: null })),
    ].sort((a, b) => dayjs(a.session.startedAt).valueOf() - dayjs(b.session.startedAt).valueOf())
    const lostClicks = (data.clicks ?? []).filter((click) => !click.session)

    return (
        <div className="flex flex-col gap-4">
            <section className="border rounded bg-surface-primary p-4 flex flex-wrap items-start gap-4">
                {data.person ? (
                    <ProfilePicture user={{ first_name: data.person.name, email: data.person.email }} size="xl" />
                ) : null}
                <div className="flex-1 min-w-60 flex flex-col gap-1">
                    <h3 className="text-lg font-semibold m-0">
                        {data.person
                            ? `What ${data.person.name.split(' ')[0]} did after this email`
                            : 'What happened after this email'}
                    </h3>
                    <p className="text-sm m-0">{summary(data)}</p>
                    {!data.person && <p className="text-xs text-secondary m-0">{NO_PERSON_TEXT}</p>}
                    <p className="text-xs text-secondary m-0">
                        “{data.subject}” · delivered{' '}
                        <TZLabel time={data.deliveredAt} formatDate="MMM D" formatTime="HH:mm" />
                    </p>
                </div>
                <div className="flex flex-wrap gap-2">
                    {data.person && (
                        <LemonButton type="secondary" size="small" to={urls.personByDistinctId(data.person.distinctId)}>
                            View person
                        </LemonButton>
                    )}
                    <LemonButton type="secondary" size="small" onClick={() => setShowEmail(!showEmail)}>
                        {showEmail ? 'Hide the email' : 'Show the email'}
                    </LemonButton>
                </div>
            </section>

            {!data.engagementEventsOn && <LemonBanner type="info">{EVENTS_OFF_TEXT}</LemonBanner>}
            {showEmail && <JourneyEmailPreview data={data} />}

            <section className="flex flex-col gap-2">
                <h4 className="text-sm font-semibold m-0">Sessions in the week after the email</h4>
                <LemonTable
                    dataSource={rows}
                    rowKey={(row) => row.session.id}
                    emptyState={data.clicks === null ? NOT_TRACKED_TEXT : NO_CLICKS_TEXT}
                    columns={[
                        {
                            title: 'Started',
                            key: 'started',
                            render: (_, row) => (
                                <TZLabel time={row.session.startedAt} formatDate="MMM D" formatTime="HH:mm" />
                            ),
                        },
                        {
                            title: 'From this email?',
                            key: 'from',
                            render: (_, row) =>
                                row.click ? (
                                    <div className="flex flex-col gap-0.5 py-1">
                                        <LemonTag type="success">
                                            Clicked “{linkFor(data, row.click.linkKey).label}”
                                        </LemonTag>
                                        {whoText(row.session, data) && (
                                            <span className="text-xs text-secondary max-w-60">
                                                {whoText(row.session, data)}
                                            </span>
                                        )}
                                    </div>
                                ) : (
                                    <LemonTag type="muted">Came back on their own</LemonTag>
                                ),
                        },
                        {
                            title: 'Session',
                            key: 'session',
                            render: (_, row) => (
                                <div className="flex flex-col text-xs">
                                    <code>{row.session.landing.split('?')[0]}</code>
                                    <span className="text-secondary">
                                        {humanFriendlyDuration(row.session.durationSeconds)} · {row.session.pages} pages
                                        · {row.session.device}
                                    </span>
                                </div>
                            ),
                        },
                        {
                            title: 'Did',
                            key: 'did',
                            render: (_, row) => (
                                <div className="flex flex-wrap gap-1">
                                    {row.session.events
                                        .filter((event) => event.outcome)
                                        .map((event) => (
                                            <LemonTag key={event.at}>{event.label}</LemonTag>
                                        ))}
                                </div>
                            ),
                        },
                        {
                            key: 'watch',
                            align: 'right',
                            render: (_, row) =>
                                row.session.recording ? (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconPlayFilled />}
                                        onClick={() => setWatching(row.session)}
                                    >
                                        Watch
                                    </LemonButton>
                                ) : (
                                    <span className="text-xs text-secondary">No recording</span>
                                ),
                        },
                    ]}
                />
                {lostClicks.length > 0 && (
                    <div className="flex flex-col gap-1 text-xs text-secondary">
                        {lostClicks.map((click) => {
                            const link = linkFor(data, click.linkKey)
                            return (
                                <span key={click.id}>
                                    Clicked “{link.label}”{' '}
                                    <TZLabel time={click.at} formatDate="MMM D" formatTime="HH:mm" />:{' '}
                                    {noSessionText(click, link, data)}
                                </span>
                            )
                        })}
                    </div>
                )}
            </section>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
