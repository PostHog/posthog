// PROTOTYPE (ticket #385), throwaway. Variant A: the page leads with the clicks, and each click carries the
// session it started, inline. The email and the person move to the side.
import { useState } from 'react'

import { IconCursorClick, IconExternal, IconLetter } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EVENTS_OFF_TEXT, NO_CLICKS_TEXT, NO_PERSON_TEXT, NOT_TRACKED_TEXT, noSessionText } from './journeyCopy'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { JourneyData, JourneySession, linkFor, sessionsFromClicks } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'
import { JourneySessionSummary } from './JourneySessionSummary'

function DeliveryStrip({ data }: { data: JourneyData }): JSX.Element {
    const steps: [string, string | null][] = [
        ['Sent', data.sentAt],
        ['Delivered', data.deliveredAt],
        ['Opened', data.openedAt],
    ]
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm border rounded bg-surface-primary px-4 py-2">
            {steps.map(([label, at]) => (
                <span key={label} className={at ? undefined : 'text-secondary'}>
                    <span className="font-semibold">{label}</span>{' '}
                    {at ? (
                        <TZLabel time={at} formatDate="MMM D" formatTime="HH:mm" />
                    ) : (
                        <span>{data.clicks === null ? 'not tracked' : 'not yet'}</span>
                    )}
                </span>
            ))}
            <span>
                <span className="font-semibold">Clicked</span>{' '}
                <span>
                    {data.clicks === null
                        ? 'not tracked'
                        : data.clicks.length
                          ? pluralize(data.clicks.length, 'time')
                          : 'not yet'}
                </span>
            </span>
        </div>
    )
}

export function VariantClickTimeline({ data }: { data: JourneyData }): JSX.Element {
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const clicks = data.clicks
    const sessions = sessionsFromClicks(data)

    return (
        <div className="@container flex flex-col gap-4">
            <DeliveryStrip data={data} />
            <div className="flex flex-col @3xl:flex-row gap-4 items-start">
                <section className="w-full @3xl:flex-1 min-w-0 border rounded bg-surface-primary p-4 flex flex-col gap-3">
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
                                <span className="text-sm text-secondary">
                                    Email delivered{' '}
                                    <TZLabel time={data.deliveredAt} formatDate="MMM D" formatTime="HH:mm" />
                                    {data.openedAt && (
                                        <>
                                            {' '}
                                            · opened{' '}
                                            <TZLabel time={data.openedAt} formatDate="MMM D" formatTime="HH:mm" />
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
                                                    <TZLabel time={click.at} formatDate="MMM D" formatTime="HH:mm" />
                                                </span>
                                                <span className="text-xs text-secondary truncate flex items-center gap-1">
                                                    <IconExternal /> {link.url.replace('https://', '')}
                                                </span>
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
                <div className="w-full @3xl:w-80 shrink-0 flex flex-col gap-4">
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
                    <JourneyEmailPreview data={data} compact />
                </div>
            </div>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
