// PROTOTYPE (ticket #385), throwaway. Variant D: numbers first. The funnel from sent to the conversion event, then
// each link, then what Replay vision found in the sessions the email started.
import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { FindingCard, ScannerSetup, ScannerStatus, ScannerSummary } from './ImpactFindings'
import { ImpactData } from './impactFixtures'
import { GoalPicker, ImpactFunnel, ImpactLift } from './ImpactFunnel'
import { ImpactLinkTable } from './ImpactLinkTable'
import type { JourneySession } from './journeyFixtures'
import { JourneyRecordingModal } from './JourneyRecordingModal'

export function VariantImpactFunnel({ data }: { data: ImpactData }): JSX.Element {
    const [watching, setWatching] = useState<JourneySession | null>(null)
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <GoalPicker data={data} />
                <LemonTag type="muted">{data.period}</LemonTag>
            </div>
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-base font-semibold m-0">
                    From send to {data.goal ? `"${data.goal.event}"` : 'conversion'}
                </h3>
                <ImpactFunnel data={data} layout="bars" />
                <ImpactLift data={data} />
            </section>
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-base font-semibold m-0">Links</h3>
                <ImpactLinkTable data={data} />
            </section>
            <section className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <h3 className="text-base font-semibold m-0">What people did after clicking</h3>
                {data.scanner ? (
                    <>
                        <ScannerStatus data={data} />
                        <ScannerSummary data={data} />
                        <div className="grid grid-cols-1 @3xl:grid-cols-2 gap-3">
                            {data.scanner.findings.map((finding) => (
                                <FindingCard key={finding.id} finding={finding} data={data} onWatch={setWatching} />
                            ))}
                        </div>
                    </>
                ) : (
                    <ScannerSetup data={data} />
                )}
            </section>
            <JourneyRecordingModal session={watching} onClose={() => setWatching(null)} />
        </div>
    )
}
