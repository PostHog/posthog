import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EvaluationPattern, EvaluationRun } from '../types'

export interface PatternCardProps {
    pattern: EvaluationPattern
    type: 'pass' | 'fail' | 'na'
    runsLookup: Record<string, EvaluationRun>
}

export function PatternCard({ pattern, type, runsLookup }: PatternCardProps): JSX.Element {
    const borderClass = type === 'pass' ? 'border-success' : type === 'fail' ? 'border-danger' : 'border-muted'
    const iconClass = type === 'pass' ? 'text-success' : type === 'fail' ? 'text-danger' : 'text-muted'
    const Icon = type === 'pass' ? IconCheck : type === 'fail' ? IconX : IconMinus

    return (
        <div className={`border rounded-lg p-3 ${borderClass}`}>
            <div className="flex items-center gap-2 mb-2">
                <Icon className={iconClass} />
                <span className="font-semibold">{pattern.title}</span>
                <span className="text-xs text-muted bg-bg-light px-2 py-0.5 rounded">{pattern.frequency}</span>
            </div>
            <p className="text-sm text-default mb-2">{pattern.description}</p>
            {pattern.example_generation_ids.length > 0 && (
                <div className="mt-2 flex items-baseline gap-1.5 flex-wrap">
                    <span className="text-xs text-muted">Generations:</span>
                    {pattern.example_generation_ids.map((genId) => {
                        const run = runsLookup[genId]
                        if (run) {
                            return (
                                <Tooltip key={genId} title={run.reasoning}>
                                    <Link
                                        to={
                                            combineUrl(urls.llmAnalyticsTrace(run.trace_id), {
                                                ...router.values.searchParams,
                                                event: genId,
                                                tab: 'evals',
                                            }).url
                                        }
                                        className="text-xs font-mono text-primary hover:underline"
                                        data-attr="llma-evaluation-summary-example-link"
                                        onClick={() => {
                                            posthog.capture('llma evaluation summary example clicked', {
                                                pattern_type: type,
                                                pattern_title: pattern.title,
                                            })
                                        }}
                                    >
                                        {genId.slice(0, 8)}
                                    </Link>
                                </Tooltip>
                            )
                        }
                        return (
                            <span key={genId} className="text-xs font-mono text-muted">
                                {genId.slice(0, 8)}
                            </span>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
