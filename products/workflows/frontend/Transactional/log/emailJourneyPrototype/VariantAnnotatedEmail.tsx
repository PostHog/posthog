// PROTOTYPE (ticket #385), throwaway. Variant C: the email itself is the page. Each link carries its clicks;
// picking a link opens a side panel with the sessions those clicks started.
import { useState } from 'react'

import { IconCursorClick } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EVENTS_OFF_TEXT, NO_CLICKS_TEXT, NO_PERSON_TEXT, NOT_TRACKED_TEXT, noSessionText } from './journeyCopy'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { JourneyData, JourneyLink, JourneySession } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'
import { JourneySessionSummary } from './JourneySessionSummary'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'

export function VariantAnnotatedEmail({ data }: { data: JourneyData }): JSX.Element {
    const prototype = useEmailJourneyPrototype()
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const clicks = data.clicks ?? []
    const defaultLink = clicks[0]?.linkKey ?? null
    const selectedKey = prototype.link ?? defaultLink
    const selected = data.links.find((link) => link.key === selectedKey) ?? null
    const selectedClicks = clicks.filter((click) => click.linkKey === selectedKey)

    const renderLink = (link: JourneyLink): JSX.Element => {
        const count = clicks.filter((click) => click.linkKey === link.key).length
        const sessions = clicks.filter((click) => click.linkKey === link.key && click.session).length
        const isSelected = link.key === selectedKey
        return (
            <span className="inline-flex flex-wrap items-center gap-1 align-middle">
                <span className="text-[#2f80fa] underline">{link.label}</span>
                {data.clicks !== null && (
                    // Light chip on the white email body, so it reads the same in both app themes.
                    <button
                        type="button"
                        onClick={() => prototype.set({ link: link.key })}
                        className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-semibold cursor-pointer ${
                            isSelected
                                ? 'bg-[#1d4aff] text-white border-[#1d4aff]'
                                : count
                                  ? 'bg-[#eef2ff] text-[#1d4aff] border-[#c7d2fe]'
                                  : 'bg-[#f3f4f6] text-[#6b7280] border-[#e5e7eb]'
                        }`}
                        data-attr="prototype-journey-link-badge"
                    >
                        <IconCursorClick />
                        {count ? `${pluralize(count, 'click')} · ${pluralize(sessions, 'session')}` : 'No clicks'}
                    </button>
                )}
            </span>
        )
    }

    return (
        <div className="@container flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <span>
                    Delivered <TZLabel time={data.deliveredAt} formatDate="MMM D" formatTime="HH:mm" />
                </span>
                <span className={data.openedAt ? undefined : 'text-secondary'}>
                    {data.openedAt ? (
                        <>
                            Opened <TZLabel time={data.openedAt} formatDate="MMM D" formatTime="HH:mm" />
                        </>
                    ) : (
                        'Opens not tracked'
                    )}
                </span>
                <span className="text-secondary">
                    {data.person ? (
                        <>
                            To {data.person.name} ·{' '}
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                to={urls.personByDistinctId(data.person.distinctId)}
                                className="inline-flex"
                            >
                                View person
                            </LemonButton>
                        </>
                    ) : (
                        `To ${data.recipient}, not linked to a person`
                    )}
                </span>
            </div>
            {!data.engagementEventsOn && <LemonBanner type="info">{EVENTS_OFF_TEXT}</LemonBanner>}
            {data.clicks === null && <LemonBanner type="info">{NOT_TRACKED_TEXT}</LemonBanner>}
            {data.clicks?.length === 0 && <LemonBanner type="info">{NO_CLICKS_TEXT}</LemonBanner>}
            <div className="flex flex-col @3xl:flex-row gap-4 items-start">
                <div className="w-full @3xl:flex-1 min-w-0">
                    <JourneyEmailPreview data={data} renderLink={renderLink} />
                </div>
                {data.clicks !== null && data.clicks.length > 0 && (
                    <aside className="w-full @3xl:w-[26rem] shrink-0 border rounded bg-surface-primary p-4 flex flex-col gap-3">
                        {selected ? (
                            <>
                                <div className="flex flex-col gap-0.5">
                                    <h3 className="text-base font-semibold m-0">“{selected.label}”</h3>
                                    <span className="text-xs text-secondary truncate">{selected.url}</span>
                                </div>
                                {!data.person && <span className="text-xs text-secondary">{NO_PERSON_TEXT}</span>}
                                {selectedClicks.length === 0 ? (
                                    <span className="text-sm text-secondary">Nobody clicked this link yet.</span>
                                ) : (
                                    selectedClicks.map((click) => (
                                        <div key={click.id} className="border-t pt-3 flex flex-col gap-2">
                                            <span className="text-sm">
                                                Clicked{' '}
                                                <TZLabel time={click.at} formatDate="MMM D" formatTime="HH:mm" />
                                            </span>
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
                                                        {noSessionText(click, selected, data)}
                                                    </span>
                                                </div>
                                            )}
                                        </div>
                                    ))
                                )}
                            </>
                        ) : (
                            <span className="text-sm text-secondary">Pick a link in the email to see its clicks.</span>
                        )}
                    </aside>
                )}
            </div>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
