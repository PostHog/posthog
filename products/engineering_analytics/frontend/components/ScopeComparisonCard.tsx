// A scope-against-repo card: one author's or one team's figure next to the same figure over the whole
// repository. The question is "is this unusual here", so the graphic is two labeled bars on a shared
// zero-based scale. Use WindowComparisonCard when the question is this window against the previous one.

import { ReactNode } from 'react'

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { ScopeRepoFigureApi } from '../generated/api.schemas'
import { ComparisonBarRow } from './ComparisonBarRow'

export function ScopeComparisonCard({
    title,
    tooltip,
    scopeLabel,
    figure,
    formatValue,
    caption,
    loading = false,
    emptyText,
}: {
    title: string
    /** Definition or methodology, shown on title hover. */
    tooltip?: ReactNode
    scopeLabel: string
    figure: ScopeRepoFigureApi | null | undefined
    formatValue: (value: number) => string
    /** The totals behind the figure, under the bars. */
    caption?: ReactNode
    loading?: boolean
    emptyText: string
}): JSX.Element {
    const scope = figure?.scope
    const repo = figure?.repo
    const max = Math.max(scope ?? 0, repo ?? 0)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                {tooltip ? (
                    <Tooltip title={tooltip}>
                        <span className="cursor-default">{title}</span>
                    </Tooltip>
                ) : (
                    title
                )}
            </h3>
            {loading ? (
                <LemonSkeleton className="h-20 w-full" />
            ) : scope != null ? (
                <>
                    <div className="mb-3 flex flex-wrap items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">{formatValue(scope)}</span>
                        {repo != null && (
                            <span className="text-xs tabular-nums text-tertiary">repo {formatValue(repo)}</span>
                        )}
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <ComparisonBarRow label={scopeLabel} value={scope} max={max} formatValue={formatValue} />
                        {repo != null && (
                            <ComparisonBarRow label="Repo" value={repo} max={max} formatValue={formatValue} muted />
                        )}
                    </div>
                    {caption && <div className="mt-2 text-[11px] tabular-nums text-tertiary">{caption}</div>}
                </>
            ) : (
                <div className="flex h-20 items-center text-xs text-secondary">{emptyText}</div>
            )}
        </LemonCard>
    )
}
