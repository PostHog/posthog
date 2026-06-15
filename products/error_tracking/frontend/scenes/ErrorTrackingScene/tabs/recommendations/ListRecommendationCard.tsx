import { ReactNode } from 'react'

import { RecommendationCard, RecommendationCardProps } from './RecommendationCard'

export interface ListRecommendationItem {
    key: string
    enabled: boolean
    name: string
    reason?: string
    action?: ReactNode
}

export interface ListRecommendationCardProps extends Omit<
    RecommendationCardProps,
    'progress' | 'children' | 'description'
> {
    description?: string
    items: ListRecommendationItem[]
    progressLabel: string
}

export function ListRecommendationCard({
    items,
    progressLabel,
    ...cardProps
}: ListRecommendationCardProps): JSX.Element {
    const enabledCount = items.filter((i) => i.enabled).length

    return (
        <RecommendationCard
            {...cardProps}
            progress={{ current: enabledCount, total: items.length, label: progressLabel }}
        >
            <div className="flex flex-col gap-0">
                {items.map((item) => (
                    <div
                        key={item.key}
                        className={`flex items-center gap-3 py-2 border-b last:border-b-0 ${item.enabled ? 'opacity-60' : ''}`}
                    >
                        <div
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${item.enabled ? 'bg-success' : 'bg-muted'}`}
                        />
                        <div className="flex-1">
                            <span className="text-sm font-medium">{item.name}</span>
                            {item.reason && <p className="text-xs text-muted m-0">{item.reason}</p>}
                        </div>
                        {!item.enabled && item.action}
                    </div>
                ))}
            </div>
        </RecommendationCard>
    )
}
