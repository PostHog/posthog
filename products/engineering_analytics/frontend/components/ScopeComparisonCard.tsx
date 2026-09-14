// A scope-against-repo card: one author's or one team's figure next to the same figure over the whole
// repository. The question is "is this unusual here", so the graphic is two labeled bars on a shared
// zero-based scale. Window-over-window comparisons use WindowComparisonCard instead.

import { ReactNode } from 'react'

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import type { ScopeRepoFigureApi } from '../generated/api.schemas'

function ComparisonRow({
    label,
    value,
    max,
    formatValue,
    isScope,
    marker,
    markerLabel,
}: {
    label: string
    value: number
    max: number
    formatValue: (value: number) => string
    isScope: boolean
    marker?: number | null
    markerLabel?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="w-20 shrink-0 text-[11px] text-tertiary">{label}</span>
            <div className="relative h-2.5 flex-1 rounded-sm">
                <div
                    className={`h-full rounded-sm ${isScope ? 'bg-[var(--data-color-1)]' : 'bg-[var(--muted)]'}`}
                    style={{ width: `${Math.max(max > 0 ? (value / max) * 100 : 0, 2)}%` }}
                />
                {marker != null && max > 0 && (
                    <Tooltip title={`${markerLabel} ${formatValue(marker)}`}>
                        <div
                            className="absolute -top-0.5 h-3.5 w-0.5 -translate-x-1/2 rounded-sm bg-[var(--text-3000)]"
                            style={{ left: `${(marker / max) * 100}%` }}
                        />
                    </Tooltip>
                )}
            </div>
            <span className="w-14 shrink-0 text-right text-xs font-medium tabular-nums">{formatValue(value)}</span>
        </div>
    )
}

export function ScopeComparisonCard({
    title,
    tooltip,
    scopeLabel,
    figure,
    formatValue,
    marker,
    markerLabel,
    caption,
    loading = false,
    emptyText,
    dataAttr,
}: {
    title: string
    /** Definition or methodology, shown on title hover. */
    tooltip?: ReactNode
    /** The row label for the scope's bar, e.g. "This author" or "This team". */
    scopeLabel: string
    figure: ScopeRepoFigureApi | null | undefined
    formatValue: (value: number) => string
    /** A companion figure (e.g. p90) pinned as a tick on each bar, on the same scale. */
    marker?: ScopeRepoFigureApi | null
    markerLabel?: string
    /** The totals behind the figure, under the bars. */
    caption?: ReactNode
    loading?: boolean
    emptyText: string
    dataAttr?: string
}): JSX.Element {
    const scope = figure?.scope
    const repo = figure?.repo
    const max = Math.max(...[scope, repo, marker?.scope, marker?.repo].map((value) => value ?? 0))

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-4" data-attr={dataAttr}>
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
                        <ComparisonRow
                            label={scopeLabel}
                            value={scope}
                            max={max}
                            formatValue={formatValue}
                            isScope
                            marker={marker?.scope}
                            markerLabel={markerLabel}
                        />
                        {repo != null && (
                            <ComparisonRow
                                label="Repo"
                                value={repo}
                                max={max}
                                formatValue={formatValue}
                                isScope={false}
                                marker={marker?.repo}
                                markerLabel={markerLabel}
                            />
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
