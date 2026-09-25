import { LemonBanner, LemonCollapse, LemonModal } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ScoutTrialResultApi } from 'products/signals/frontend/generated/api.schemas'

import { trialReportText } from './scoutTrialUtils'

export function ScoutTrialResultModal({
    result,
    onClose,
}: {
    result: ScoutTrialResultApi | null
    onClose: () => void
}): JSX.Element | null {
    if (!result) {
        return null
    }
    const memory = Object.entries(result.memory)

    return (
        <LemonModal isOpen onClose={onClose} title="Run results" width={760} className="ph-no-capture ph-replay-block">
            <div className="flex flex-col gap-4 min-w-0 break-words">
                <div className="text-muted text-sm">
                    <span>{`${result.model} · ${result.reasoning_effort} effort · ${result.status}`}</span>
                </div>
                {(result.error || result.invalid_reason) && (
                    <LemonBanner type="error">{result.error || result.invalid_reason}</LemonBanner>
                )}
                {result.export_error && (
                    <LemonBanner type="warning">
                        The saved export needs a retry. These inline results are still available to download.
                    </LemonBanner>
                )}
                <LemonCollapse
                    defaultActiveKeys={['summary', 'reports']}
                    multiple
                    panels={[
                        {
                            key: 'summary',
                            header: 'Run summary',
                            content: (
                                <LemonMarkdown disableImages="all">
                                    {result.summary || 'The scout has not written a summary yet.'}
                                </LemonMarkdown>
                            ),
                        },
                        {
                            key: 'reports',
                            header: `Captured reports (${result.reports.length})`,
                            content: result.reports.length ? (
                                <div className="flex flex-col gap-4">
                                    {result.reports.map((report) => (
                                        <div key={report.id} className="border-b last:border-b-0 pb-3">
                                            <h4 className="break-words">
                                                {typeof report.document.title === 'string'
                                                    ? report.document.title
                                                    : 'Captured report'}
                                            </h4>
                                            <LemonMarkdown disableImages="all">
                                                {trialReportText(report.document)}
                                            </LemonMarkdown>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p>No reports captured.</p>
                            ),
                        },
                        {
                            key: 'memory',
                            header: `Private memory changes (${memory.length})`,
                            content: memory.length ? (
                                <div className="flex flex-col gap-3">
                                    {memory.map(([key, entry]) => (
                                        <div key={key}>
                                            <strong className="break-all">{key}</strong>
                                            <p className="whitespace-pre-wrap break-words">
                                                {entry?.content ?? 'Deleted in this run'}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <p>No memory changes recorded.</p>
                            ),
                        },
                        {
                            key: 'details',
                            header: 'Run details',
                            content: (
                                <pre className="whitespace-pre-wrap break-all text-xs">
                                    {JSON.stringify(
                                        {
                                            launch_id: result.launch_id,
                                            context_id: result.context_id,
                                            skill_body_sha256: result.skill_body_sha256,
                                            run_id: result.run_id,
                                            task_id: result.task_id,
                                            task_run_id: result.task_run_id,
                                            started_at: result.started_at,
                                            completed_at: result.completed_at,
                                            input_tokens: result.input_tokens,
                                            output_tokens: result.output_tokens,
                                            cost_usd: result.cost_usd,
                                        },
                                        null,
                                        2
                                    )}
                                </pre>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
