// PROTOTYPE (ticket #385), throwaway. Variant E: findings first. What Replay vision saw in the sessions this email
// started leads the page; the numbers sit in a side rail.
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { FindingCard, ScannerSetup, ScannerStatus, ScannerSummary } from './ImpactFindings'
import { ImpactData } from './impactFixtures'
import { GoalPicker, ImpactFunnel, ImpactLift } from './ImpactFunnel'
import { ImpactLinkTable } from './ImpactLinkTable'
import type { JourneySession } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'

const TONE_ORDER = { problem: 0, neutral: 1, success: 2 }

export function VariantImpactFindings({ data }: { data: ImpactData }): JSX.Element {
    const [watching, setWatching] = useState<JourneySession | null>(null)
    const findings = [...(data.scanner?.findings ?? [])].sort(
        (a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone] || b.sessions - a.sessions
    )
    return (
        <div className="flex flex-col @4xl:flex-row gap-4 items-start">
            <div className="w-full @4xl:flex-1 min-w-0 flex flex-col gap-4">
                {data.scanner ? (
                    <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                        <h3 className="text-base font-semibold m-0 flex items-center gap-2">
                            <IconSparkles /> What happened after people clicked
                        </h3>
                        <ScannerSummary data={data} />
                        <ScannerStatus data={data} />
                    </section>
                ) : (
                    <ScannerSetup data={data} />
                )}
                {findings.map((finding) => (
                    <FindingCard key={finding.id} finding={finding} data={data} onWatch={setWatching} excerpts={2} />
                ))}
                <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                    <h3 className="text-base font-semibold m-0">Links</h3>
                    <ImpactLinkTable data={data} />
                </section>
            </div>
            <div className="w-full @4xl:w-96 shrink-0 flex flex-col gap-4">
                <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-2">
                        <h3 className="text-sm font-semibold m-0">This email in numbers</h3>
                        <LemonTag type="muted">{data.period}</LemonTag>
                    </div>
                    <ImpactFunnel data={data} layout="list" />
                    <GoalPicker data={data} />
                    <ImpactLift data={data} />
                </section>
            </div>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
