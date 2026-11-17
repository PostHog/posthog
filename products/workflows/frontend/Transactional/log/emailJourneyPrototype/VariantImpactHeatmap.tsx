// PROTOTYPE (ticket #385), throwaway. Variant F: the email is the page. Each link carries its numbers, shaded by
// how many people clicked it; picking a link opens what happened after that link.
import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { FindingCard, ScannerSetup, ScannerStatus } from './ImpactFindings'
import { ImpactData, percent } from './impactFixtures'
import { GoalPicker, ImpactFunnel, ImpactLift } from './ImpactFunnel'
import { JourneyEmailPreview } from './JourneyEmailPreview'
import { journeyData, JourneySession } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'

export function VariantImpactHeatmap({ data }: { data: ImpactData }): JSX.Element {
    const { link: selectedKey, set } = useEmailJourneyPrototype()
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const email = journeyData('full')
    const selected = data.links.find((link) => link.key === selectedKey) ?? null
    const maxClicked = Math.max(1, ...data.links.map((link) => link.clickedPeople))
    const findings = (data.scanner?.findings ?? []).filter((finding) => finding.linkKey === selected?.key)

    return (
        <div className="@container flex flex-col gap-4">
            <ImpactFunnel data={data} layout="strip" />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <GoalPicker data={data} />
                <LemonTag type="muted">{data.period}</LemonTag>
            </div>
            <div className="flex flex-col @4xl:flex-row gap-4 items-start">
                <div className="w-full @4xl:flex-1 min-w-0">
                    <JourneyEmailPreview
                        data={email}
                        to={`${humanFriendlyNumber(data.sent)} recipients`}
                        renderLink={(link) => {
                            const stats = data.links.find((l) => l.key === link.key)
                            const heat = stats ? stats.clickedPeople / maxClicked : 0
                            return (
                                <span className="inline-flex items-center gap-1 flex-wrap">
                                    <span className="text-[#2f80fa] underline">{link.label}</span>
                                    {stats && (
                                        <button
                                            type="button"
                                            onClick={() => set({ link: link.key === selectedKey ? null : link.key })}
                                            className={`cursor-pointer rounded px-1.5 py-0.5 text-xs font-semibold border ${
                                                link.key === selectedKey ? 'border-black' : 'border-transparent'
                                            }`}
                                            style={{ background: `rgba(245, 78, 0, ${0.12 + heat * 0.5})` }}
                                            data-attr="prototype-impact-link-chip"
                                        >
                                            {humanFriendlyNumber(stats.clickedPeople)} clicked
                                            {stats.converted !== null && data.goal
                                                ? ` · ${humanFriendlyNumber(stats.converted)} ${data.goal.event}`
                                                : ''}
                                        </button>
                                    )}
                                </span>
                            )
                        }}
                    />
                </div>
                <div className="w-full @4xl:w-[28rem] shrink-0 flex flex-col gap-3">
                    {!selected ? (
                        <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                            <h3 className="text-base font-semibold m-0">
                                {data.links.length ? 'Pick a link in the email' : 'Link clicks not tracked'}
                            </h3>
                            <p className="text-sm text-secondary m-0">
                                {data.links.length
                                    ? 'Each link shows who clicked it and who converted. Pick one to see what those people did next.'
                                    : "Clicks aren't tracked for this email, so the links carry no numbers."}
                            </p>
                            <ImpactLift data={data} />
                            {data.scanner ? <ScannerStatus data={data} /> : <ScannerSetup data={data} />}
                        </section>
                    ) : (
                        <>
                            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                                <h3 className="text-base font-semibold m-0">"{selected.label}"</h3>
                                <span className="text-xs text-secondary">{selected.url.replace('https://', '')}</span>
                                <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
                                    <dt>Clicked</dt>
                                    <dd className="m-0 text-right font-semibold">
                                        {humanFriendlyNumber(selected.clickedPeople)}
                                    </dd>
                                    <dt>Started a session</dt>
                                    <dd className="m-0 text-right font-semibold">
                                        {!selected.tagged
                                            ? 'Off your site'
                                            : selected.sessions === null
                                              ? 'Needs link tagging'
                                              : humanFriendlyNumber(selected.sessions)}
                                    </dd>
                                    <dt>{data.goal?.event ?? 'Converted'}</dt>
                                    <dd className="m-0 text-right font-semibold">
                                        {selected.converted === null
                                            ? '-'
                                            : `${humanFriendlyNumber(selected.converted)} (${percent(selected.converted, selected.clickedPeople)})`}
                                    </dd>
                                </dl>
                            </section>
                            {data.scanner ? (
                                findings.length ? (
                                    findings.map((finding) => (
                                        <FindingCard
                                            key={finding.id}
                                            finding={finding}
                                            data={data}
                                            onWatch={setWatching}
                                        />
                                    ))
                                ) : (
                                    <p className="text-sm text-secondary m-0">
                                        {selected.tagged
                                            ? 'No findings for this link yet.'
                                            : 'This link leaves your site, so there are no sessions to scan.'}
                                    </p>
                                )
                            ) : (
                                <ScannerSetup data={data} />
                            )}
                        </>
                    )}
                </div>
            </div>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
