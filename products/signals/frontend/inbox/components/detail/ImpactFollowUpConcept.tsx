import { useState } from 'react'

import { LemonButton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonProgressCircle } from 'lib/lemon-ui/LemonProgressCircle'

import type { FollowUpStage, ImpactFollowUpExample } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactTrendChart } from './ImpactTrendChart'

export interface ImpactFollowUpConceptProps {
    example: ImpactFollowUpExample
    stage: FollowUpStage
    version: 'trend' | 'countdown' | 'checkpoints'
}

export function ImpactFollowUpConcept({ example, stage, version }: ImpactFollowUpConceptProps): JSX.Element {
    const [trackingEnabled, setTrackingEnabled] = useState(false)
    const [actionTaken, setActionTaken] = useState(false)
    const finished = stage === 'finished'
    const watching = stage === 'watching'
    const days = stage === 'planned' ? 0 : watching ? example.elapsedDays : example.windowDays
    const sample = stage === 'planned' ? 0 : watching ? example.watchingSample : example.finishedSample
    const timePercent = (days / example.windowDays) * 100
    const samplePercent = Math.min((sample / example.sampleNeeded) * 100, 100)
    const result = finished
        ? example.verdict === 'met'
            ? 'Worked'
            : example.verdict === 'failed'
              ? 'Did not work'
              : 'Not enough proof'
        : watching
          ? 'Watching for impact'
          : 'Before release'
    const resultType = finished
        ? example.verdict === 'met'
            ? 'success'
            : example.verdict === 'failed'
              ? 'danger'
              : 'caution'
        : 'warning'
    const bodyText = stage === 'planned' ? example.goalShort : watching ? example.watchingNote : example.resultNote
    const value = stage === 'planned' ? example.baseline : watching ? example.watchingValue : example.finishedValue
    const signalRows = example.evidence.map((row) => (
        <div key={row.signal} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-primary py-2 text-sm">
            <div className="min-w-0">
                <span className="font-medium">{row.signal}</span>
                <span className="ml-2 text-secondary">{stage === 'planned' ? row.baseline : watching ? row.watching : row.finished}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
                <span className="text-tertiary">Goal {row.target}</span>
                {finished && (
                    <LemonTag size="small" type={row.result === 'met' ? 'success' : row.result === 'failed' ? 'danger' : 'caution'}>
                        {row.result === 'met' ? 'Met' : row.result === 'failed' ? 'Missed' : 'Unknown'}
                    </LemonTag>
                )}
                {watching && row.result === 'missing' && (row.watching === '0' || row.watching === '0 / 0' || row.watching === 'No signal') && (
                    <LemonTag size="small" type="caution">No data yet</LemonTag>
                )}
            </div>
        </div>
    ))

    const timeTrack = (
        <div className="flex flex-col gap-1.5">
            <div className="flex justify-between gap-3 text-xs">
                <span className="font-semibold">Time since release</span>
                <span>{stage === 'planned' ? `Proposed ${example.decisionDate}` : `${days} of ${example.windowDays} days · ${example.decisionDate}`}</span>
            </div>
            <LemonProgress percent={timePercent} smoothing={false} />
        </div>
    )
    const sampleTrack = (
        <div className="flex flex-col gap-1.5">
            <div className="flex justify-between gap-3 text-xs">
                <span className="font-semibold">{example.sampleLabel}</span>
                <span>{stage === 'planned' ? `Need ${example.sampleNeeded}` : `${sample} / ${example.sampleNeeded} needed`}</span>
            </div>
            <LemonProgress percent={samplePercent} strokeColor="var(--success)" smoothing={false} />
        </div>
    )
    const calendar = (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap justify-between gap-2 text-xs">
                <span className="font-semibold">Days after release</span>
                <span className="text-secondary">Color = data · outline = coming · dash = missing</span>
            </div>
            <div className="flex flex-wrap gap-1.5" role="list" aria-label="Days in the watch window">
                {example.afterTrend.map((point, index) => {
                    const pending = stage === 'planned' || (watching && index >= example.elapsedDays)
                    const missing = !pending && !Number.isFinite(point)
                    const cellColor = pending
                        ? 'border-primary bg-surface-primary text-tertiary'
                        : missing
                          ? 'border-warning bg-warning-highlight text-warning'
                          : example.chartGoal !== null && point > example.chartGoal && example.chartGoal === 0
                            ? 'border-danger bg-danger-highlight text-danger'
                            : 'border-success bg-success-highlight text-success'
                    return (
                        <span
                            key={index}
                            role="listitem"
                            title={`Day ${index + 1}: ${pending ? 'not reached' : missing ? 'no data' : `${point} recorded`}`}
                            className={`flex h-8 w-8 items-center justify-center rounded border text-xs font-semibold ${cellColor}`}
                        >
                            {missing ? '–' : index + 1}
                        </span>
                    )
                })}
            </div>
        </div>
    )

    return (
        <article className="max-w-5xl" aria-label={`${example.title}: ${result}`}>
            <LemonCard hoverEffect={false} className="flex flex-col gap-5 overflow-hidden p-5 sm:p-6">
                <header className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="mb-1 text-xs text-secondary">Expected impact · {example.title}</div>
                        <h2 className="m-0 text-xl font-semibold leading-snug">{example.outcome}</h2>
                    </div>
                    <LemonTag type={resultType} size="small">{result}</LemonTag>
                </header>

                {version === 'trend' && (
                    <>
                        <div className="flex flex-wrap items-center justify-between gap-4 rounded border border-primary bg-surface-primary p-4">
                            <div>
                                <div className="text-xs text-secondary">Before release</div>
                                <div className="text-2xl font-semibold">{example.baseline}</div>
                            </div>
                            <div className="text-xl text-tertiary" aria-hidden="true">→</div>
                            <div>
                                <div className="text-xs text-secondary">{stage === 'planned' ? 'The goal' : 'Now'}</div>
                                <div className="text-3xl font-semibold">{stage === 'planned' ? example.goalShort : value}</div>
                            </div>
                        </div>
                        <div className="grid items-start gap-5 md:grid-cols-[minmax(0,2fr)_minmax(14rem,1fr)]">
                            <ImpactTrendChart example={example} stage={stage} />
                            <div className="flex flex-col gap-5 rounded border border-primary p-4">
                                <p className="m-0 text-sm leading-snug">{bodyText}</p>
                                {timeTrack}
                                {sampleTrack}
                            </div>
                        </div>
                        {finished && <div className="flex flex-wrap gap-x-5 gap-y-1">{signalRows}</div>}
                    </>
                )}

                {version === 'countdown' && (
                    <>
                        <div className="grid items-center gap-6 rounded border border-primary bg-surface-primary p-5 md:grid-cols-[minmax(0,1fr)_auto]">
                            <div>
                                <p className="m-0 text-xs font-semibold uppercase tracking-wide text-secondary">{stage === 'planned' ? 'What we want' : finished ? 'What we found' : 'What we see so far'}</p>
                                <div className="my-2 text-3xl font-semibold leading-tight">{stage === 'planned' ? example.goalShort : value}</div>
                                <p className="m-0 text-sm">{bodyText}</p>
                            </div>
                            <div className="flex items-center gap-3">
                                <div className="flex flex-col items-center gap-1.5">
                                    <LemonProgressCircle size={110} strokePercentage={0.12} progress={timePercent / 100} className={finished && example.verdict === 'met' ? 'text-success' : 'text-primary'}>
                                        <span className="flex flex-col text-center text-sm font-semibold leading-tight text-primary">
                                            <span className="text-2xl">{days}/{example.windowDays}</span>
                                            <span className="text-xs font-normal">days</span>
                                        </span>
                                    </LemonProgressCircle>
                                    <span className="text-xs text-secondary">Decision {example.decisionDate}</span>
                                </div>
                            </div>
                        </div>
                        <div className="grid items-center gap-5 md:grid-cols-[minmax(0,2fr)_minmax(14rem,1fr)]">
                            <ImpactTrendChart example={example} stage={stage} />
                            <div className="flex flex-col gap-4">
                                {sampleTrack}
                                <div className="text-xs text-secondary">{stage === 'planned' ? 'The clock starts after release.' : finished ? 'The time is up.' : `${example.windowDays - days} days left to watch.`}</div>
                                {signalRows}
                            </div>
                        </div>
                    </>
                )}

                {version === 'checkpoints' && (
                    <>
                        <div className="grid gap-2 sm:grid-cols-4">
                            {[
                                ['01', 'Before', example.baseline],
                                ['02', 'Release', stage === 'planned' ? 'Waiting for merge' : 'Shipped (mock)'],
                                ['03', 'Watch', stage === 'planned' ? `${example.windowDays} days planned` : `${days} / ${example.windowDays} days`],
                                ['04', `Decision ${example.decisionDate}`, finished ? result : 'Still ahead'],
                            ].map(([number, label, detail]) => (
                                <div key={number} className="flex flex-col gap-1 rounded border border-primary bg-surface-primary p-3">
                                    <span className="text-xs text-tertiary">{number} / {label}</span>
                                    <span className="text-sm font-semibold">{detail}</span>
                                </div>
                            ))}
                        </div>
                        <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(16rem,1fr)]">
                            <div className="flex flex-col gap-4">
                                <ImpactTrendChart example={example} stage={stage} />
                                {calendar}
                            </div>
                            <div className="flex flex-col gap-2 rounded border border-primary p-4">
                                <div className="text-xs font-semibold uppercase tracking-wide text-secondary">To call it a success</div>
                                <div className="mb-1 text-xl font-semibold">{example.goalShort}</div>
                                {signalRows}
                                <p className="mb-0 mt-auto text-sm">{bodyText}</p>
                            </div>
                        </div>
                        <div className="grid gap-4 sm:grid-cols-2">{timeTrack}{sampleTrack}</div>
                    </>
                )}

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-primary pt-3">
                    {stage === 'planned' ? (
                        <>
                            <span className="text-sm">Check again {example.window}.</span>
                            <LemonSwitch checked={trackingEnabled} onChange={setTrackingEnabled} label="Follow this impact" size="small" />
                        </>
                    ) : finished && example.verdict !== 'met' ? (
                        <>
                            <span className="text-sm">{example.verdict === 'failed' ? 'The fix did not meet its goal.' : 'We still need a clear answer.'}</span>
                            <LemonButton type="secondary" size="small" onClick={() => setActionTaken(true)}>
                                {example.verdict === 'failed' ? 'Start a new report' : 'Plan another check'}
                            </LemonButton>
                        </>
                    ) : (
                        <span className="text-sm">{finished ? 'Report resolved. Evidence stays here.' : 'Checking automatically after release.'}</span>
                    )}
                    {(trackingEnabled && stage === 'planned') || actionTaken ? (
                        <span className="w-full text-xs text-secondary">{actionTaken ? 'Draft prepared in this preview only.' : 'Following in this preview only.'}</span>
                    ) : null}
                </div>
                <details open={stage === 'planned' && version === 'checkpoints'}>
                    <summary className="cursor-pointer text-xs font-medium text-secondary">How we count this · view query</summary>
                    <div className="mt-2 flex flex-col gap-2 text-xs text-secondary">
                        <span>Start: {example.releaseGate}. Enough data: {example.minimumEvidence}.</span>
                        <pre className="m-0 overflow-x-auto rounded border border-primary bg-surface-primary p-3 text-xs leading-relaxed"><code>{example.query}</code></pre>
                        <span>Mock numbers and example events. No real report data is used.</span>
                    </div>
                </details>
            </LemonCard>
        </article>
    )
}
