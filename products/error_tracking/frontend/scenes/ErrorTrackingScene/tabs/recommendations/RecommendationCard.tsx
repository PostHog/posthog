import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { recommendationsTabLogic } from './recommendationsTabLogic'

export interface RecommendationCardProps {
    recommendationId: string
    nextRefreshAt?: string | null
    title: string
    description?: string
    progress?: { current: number; total: number; label: string }
    dismissed?: boolean
    children?: ReactNode
}

export function RecommendationCard({
    recommendationId,
    nextRefreshAt,
    title,
    description,
    progress,
    dismissed,
    children,
}: RecommendationCardProps): JSX.Element {
    const { dismissRecommendation, restoreRecommendation, refreshRecommendation } = useActions(recommendationsTabLogic)
    const canRefresh = !nextRefreshAt || new Date(nextRefreshAt) <= new Date()

    return (
        <div className="border rounded-lg bg-surface-primary p-4">
            <div className="flex items-center justify-between mb-1">
                <h3 className="font-semibold text-sm m-0">{title}</h3>
                <div className="flex items-center gap-2">
                    {progress && (
                        <>
                            <span className="text-xs text-muted">
                                {progress.current} / {progress.total} {progress.label}
                            </span>
                            <div className="w-20 h-1.5 bg-border rounded-full">
                                <div
                                    className="h-1.5 bg-success rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        width: `${progress.total === 0 ? 0 : (progress.current / progress.total) * 100}%`,
                                    }}
                                />
                            </div>
                        </>
                    )}
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconRefresh />}
                        onClick={() => refreshRecommendation(recommendationId)}
                        disabledReason={!canRefresh ? 'Too early to refresh' : undefined}
                        tooltip="Refresh this recommendation"
                    />
                    {dismissed ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => restoreRecommendation(recommendationId)}
                        >
                            Restore
                        </LemonButton>
                    ) : (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={() => dismissRecommendation(recommendationId)}
                            tooltip="Dismiss this recommendation"
                        />
                    )}
                </div>
            </div>
            {description && <p className="text-xs text-secondary mt-1 mb-3">{description}</p>}
            {children}
        </div>
    )
}
