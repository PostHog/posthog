import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import { RecommendationTile } from '../RecommendationTile'

interface IngestionFailureData {
    failedLast7Days: number
    failedLast24Hours: number
    detectedLibraries: { name: string; docUrl: string }[]
}

function openCommonProblemsDialog(): void {
    LemonDialog.open({
        title: 'Common ingestion problems',
        content: (
            <div className="space-y-3">
                <div className="rounded-lg border border-warning bg-warning-highlight p-3">
                    <p className="font-semibold text-sm mb-1">#1 — LLMs misimplement PostHog Error tracking</p>
                    <p className="text-sm text-secondary mb-2">
                        The most common issue we see is AI coding assistants (LLMs) incorrectly implementing error
                        tracking by sending{' '}
                        <code className="text-xs bg-surface-alt px-1 py-0.5 rounded">$exception_stack_trace_raw</code>{' '}
                        directly in the event. You should <strong>never</strong> be doing this.
                    </p>
                    <p className="text-sm text-secondary mb-2">
                        <strong>How to spot it:</strong> If you see{' '}
                        <code className="text-xs bg-surface-alt px-1 py-0.5 rounded">$exception_stack_trace_raw</code>{' '}
                        being set manually in your codebase, that's the problem.
                    </p>
                    <p className="text-sm text-secondary">
                        <strong>Fix:</strong> Point your LLM to our{' '}
                        <Link to="https://posthog.com/docs/error-tracking/installation" targetBlank>
                            error tracking documentation
                        </Link>{' '}
                        and ask it to reimplement using the official SDK methods.
                    </p>
                </div>
            </div>
        ),
        primaryButton: {
            children: 'Got it',
        },
        secondaryButton: null,
    })
}

export function ExceptionIngestionTile({ data }: { data: IngestionFailureData }): JSX.Element {
    return (
        <RecommendationTile
            tileId="exception-ingestion"
            icon={<IconWarning className="text-danger" />}
            title="Exception ingestion failures detected"
            category="Ingestion"
            priority="critical"
            actions={
                <>
                    <LemonButton type="primary" status="alt-dark" size="small" onClick={openCommonProblemsDialog}>
                        Common problems
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to="https://posthog.com/docs/error-tracking/installation"
                        targetBlank
                    >
                        View docs
                    </LemonButton>
                </>
            }
        >
            <div className="flex gap-4 mt-1">
                <div className="flex flex-col items-center rounded-lg bg-surface-alt px-4 py-2 flex-1">
                    <span className="text-2xl font-bold text-danger">{data.failedLast7Days}</span>
                    <span className="text-xs text-secondary">failed last 7 days</span>
                </div>
                <div className="flex flex-col items-center rounded-lg bg-surface-alt px-4 py-2 flex-1">
                    <span className="text-2xl font-bold text-warning">{data.failedLast24Hours}</span>
                    <span className="text-xs text-secondary">failed last 24h</span>
                </div>
            </div>

            {data.detectedLibraries.length > 0 ? (
                <div className="mt-2">
                    <p className="text-xs font-medium text-secondary mb-1">Detected libraries with failures:</p>
                    <div className="space-y-1">
                        {data.detectedLibraries.map((lib) => (
                            <div
                                key={lib.name}
                                className="flex items-center justify-between bg-surface-alt rounded px-3 py-1.5"
                            >
                                <span className="text-sm font-mono">{lib.name}</span>
                                <Link to={lib.docUrl} targetBlank className="text-xs">
                                    View docs →
                                </Link>
                            </div>
                        ))}
                    </div>
                </div>
            ) : null}
        </RecommendationTile>
    )
}
