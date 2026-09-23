import { useState } from 'react'

import { LemonButton, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import type { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type {
    FollowUpStage,
    ImpactEvidence,
    ImpactFollowUpExample,
} from '../../__mocks__/impactFollowUpConceptMocks'

export interface ImpactFollowUpConceptProps {
    example: ImpactFollowUpExample
    stage: FollowUpStage
    version: 'summary' | 'evidence'
}

export function ImpactFollowUpConcept({ example, stage, version }: ImpactFollowUpConceptProps): JSX.Element {
    const [trackingEnabled, setTrackingEnabled] = useState(false)
    const [actionTaken, setActionTaken] = useState(false)
    const finished = stage === 'finished'
    const watching = stage === 'watching'
    const status =
        stage === 'planned'
            ? 'Ready to implement'
            : watching
              ? 'Watching for impact'
              : example.verdict === 'met'
                ? 'Resolved · impact demonstrated'
                : example.verdict === 'failed'
                  ? 'Reopened · impact not demonstrated'
                  : 'Follow-up needed · impact unclear'
    const statusType =
        finished && example.verdict === 'met'
            ? 'success'
            : finished && example.verdict === 'failed'
              ? 'danger'
              : finished && example.verdict === 'inconclusive'
                ? 'caution'
                : 'warning'

    const columns: LemonTableColumns<ImpactEvidence> = [
        { title: 'Check', key: 'signal', render: (_, row) => <span className="font-medium">{row.signal}</span> },
        { title: 'Before', key: 'baseline', render: (_, row) => row.baseline },
        { title: 'Success needs', key: 'target', render: (_, row) => row.target },
        {
            title: stage === 'planned' ? 'After release' : 'Observed',
            key: 'observed',
            render: (_, row) => (stage === 'planned' ? '—' : watching ? row.watching : row.finished),
        },
        {
            title: 'Check status',
            key: 'result',
            render: (_, row) => (
                <LemonTag
                    size="small"
                    type={
                        !finished
                            ? 'warning'
                            : row.result === 'met'
                              ? 'success'
                              : row.result === 'failed'
                                ? 'danger'
                                : 'caution'
                    }
                >
                    {!finished
                        ? watching && row.result === 'missing'
                            ? 'No signal yet'
                            : watching
                              ? 'Collecting'
                              : 'Not started'
                        : row.result === 'missing'
                          ? 'No proof'
                          : row.result === 'met'
                            ? 'Passed'
                            : 'Failed'}
                </LemonTag>
            ),
        },
    ]

    const query = (
        <div>
            <div className="mb-1 text-xs font-semibold text-secondary">Saved check · illustrative HogQL</div>
            <pre className="m-0 overflow-x-auto rounded border border-primary bg-surface-primary p-3 text-xs leading-relaxed">
                <code>{example.query}</code>
            </pre>
            <p className="mb-0 mt-1 text-xs text-tertiary">
                Example events and values are synthetic. The release-time parameter is filled only after deployment.
            </p>
        </div>
    )

    const table = <LemonTable dataSource={example.evidence} columns={columns} rowKey="signal" size="small" />

    const followUp = (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-primary pt-3">
            {stage === 'planned' ? (
                <>
                    <div>
                        <div className="text-sm font-medium">Follow up after release</div>
                        <div className="text-xs text-secondary">Check automatically when the release and sample gates pass.</div>
                    </div>
                    <LemonSwitch checked={trackingEnabled} onChange={setTrackingEnabled} label="Enable tracking" size="small" />
                </>
            ) : watching ? (
                <span className="text-xs text-secondary">Tracking is on. No verdict until the window and evidence gates pass.</span>
            ) : (
                <>
                    <span className="text-xs text-secondary">{example.nextStep}</span>
                    {example.verdict !== 'met' && (
                        <LemonButton type="secondary" size="small" onClick={() => setActionTaken(true)}>
                            {example.verdict === 'failed' ? 'Start follow-up report' : 'Plan another check'}
                        </LemonButton>
                    )}
                </>
            )}
            {(trackingEnabled && stage === 'planned') || actionTaken ? (
                <span className="w-full text-xs text-secondary">
                    {actionTaken ? 'Follow-up drafted in this preview only.' : 'Tracking enabled in this preview only.'}
                </span>
            ) : null}
        </div>
    )

    return (
        <article className="max-w-4xl" aria-label={`${example.title}: ${status}`}>
            <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-4">
                <header className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <div className="mb-1 text-xs text-secondary">Self-driving report · {example.title}</div>
                        <h2 className="m-0 text-lg font-semibold">Expected impact</h2>
                    </div>
                    <LemonTag size="small" type={statusType}>{status}</LemonTag>
                </header>

                {version === 'summary' ? (
                    <>
                        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-primary pb-3">
                            <div>
                                <div className="text-xs text-secondary">{example.primarySignal}</div>
                                <div className="text-2xl font-semibold">
                                    {stage === 'planned' ? example.baseline : watching ? example.watchingValue : example.finishedValue}
                                </div>
                                <div className="text-xs text-secondary">
                                    {stage === 'planned' ? 'Baseline, before release' : watching ? 'Incoming data · preliminary' : 'After measurement window'}
                                </div>
                            </div>
                            <div className="max-w-sm text-sm"><span className="font-semibold">Success:</span> {example.goal}</div>
                        </div>
                        <div className="text-sm">
                            <span className="font-semibold">{watching ? example.watchingProgress : finished ? 'Window complete' : `Suggested window: ${example.window}`}</span>
                            {watching ? ` · Target window: ${example.window}` : null}
                        </div>
                        {finished && <p className="m-0 text-sm">{example.reason}</p>}
                        {table}
                        <details open={stage === 'planned'}>
                            <summary className="cursor-pointer text-xs font-medium">View saved query and evidence gates</summary>
                            <div className="mt-3 flex flex-col gap-3">{query}</div>
                        </details>
                    </>
                ) : (
                    <>
                        <p className="m-0 text-sm">{example.goal}</p>
                        <div className="flex flex-wrap gap-x-6 gap-y-2 border-y border-primary py-3 text-xs">
                            <div><span className="font-semibold">Window:</span> {example.window}</div>
                            <div><span className="font-semibold">Progress:</span> {stage === 'planned' ? 'Starts after release' : watching ? example.watchingProgress : 'Window complete'}</div>
                        </div>
                        {table}
                        {query}
                        {finished && (
                            <div className="rounded border border-primary bg-surface-primary p-3 text-sm">
                                <strong>{example.verdict === 'met' ? 'Why this passed' : example.verdict === 'failed' ? 'Why this failed' : 'Why we cannot tell yet'}</strong>
                                <p className="mb-0 mt-1">{example.reason}</p>
                            </div>
                        )}
                    </>
                )}

                <div className="flex flex-col gap-1 text-xs text-secondary">
                    <div><span className="font-semibold">Release gate:</span> {example.releaseGate}{stage === 'planned' ? ' · pending' : ' · confirmed (mock)'}</div>
                    <div><span className="font-semibold">Minimum evidence:</span> {example.minimumEvidence}</div>
                </div>
                {followUp}
            </LemonCard>
        </article>
    )
}
