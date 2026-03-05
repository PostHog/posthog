import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconHide, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { recommendationsLogic } from './recommendationsLogic'

export type TilePriority = 'critical' | 'important' | 'setup' | 'info'

const PRIORITY_CONFIG: Record<TilePriority, { tagType: LemonTagType; label: string; borderClass: string }> = {
    critical: { tagType: 'danger', label: 'Critical', borderClass: 'border-l-danger' },
    important: { tagType: 'warning', label: 'Important', borderClass: 'border-l-warning' },
    setup: { tagType: 'primary', label: 'Setup', borderClass: 'border-l-link' },
    info: { tagType: 'muted', label: 'Tip', borderClass: 'border-l-border-bold' },
}

interface RecommendationTileProps {
    tileId: string
    icon: ReactNode
    title: string
    category: string
    priority: TilePriority
    children: ReactNode
    actions?: ReactNode
}

export function RecommendationTile({
    tileId,
    icon,
    title,
    category,
    priority,
    children,
    actions: tileActions,
}: RecommendationTileProps): JSX.Element {
    const { dismissTile, snoozeTile } = useActions(recommendationsLogic)
    const config = PRIORITY_CONFIG[priority]

    return (
        <div
            className={`break-inside-avoid mb-3 border rounded-lg bg-surface-primary border-l-4 ${config.borderClass} overflow-hidden transition-all duration-200 hover:shadow-md`}
        >
            <div className="px-4 pt-3 pb-2">
                <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="text-muted shrink-0">{icon}</span>
                        <span className="text-xs font-medium text-secondary uppercase tracking-wide truncate">
                            {category}
                        </span>
                        <LemonTag type={config.tagType} size="small">
                            {config.label}
                        </LemonTag>
                    </div>
                    <LemonMenu
                        items={[
                            {
                                label: 'Snooze for 1 day',
                                icon: <IconHide />,
                                onClick: () => snoozeTile(tileId, 1),
                            },
                            {
                                label: 'Snooze for 7 days',
                                icon: <IconHide />,
                                onClick: () => snoozeTile(tileId, 7),
                            },
                            {
                                label: 'Snooze for 30 days',
                                icon: <IconHide />,
                                onClick: () => snoozeTile(tileId, 30),
                            },
                            {
                                label: 'Dismiss permanently',
                                icon: <IconX />,
                                status: 'danger',
                                onClick: () => dismissTile(tileId),
                            },
                        ]}
                    >
                        <LemonButton size="xsmall" icon={<IconX />} noPadding className="shrink-0" />
                    </LemonMenu>
                </div>
                <h3 className="font-semibold text-sm mt-2 mb-0">{title}</h3>
            </div>

            <div className="px-4 pb-3">
                <div className="text-sm text-secondary space-y-2">{children}</div>
            </div>

            {tileActions ? <div className="px-4 pb-3 pt-0 flex flex-wrap items-center gap-2">{tileActions}</div> : null}
        </div>
    )
}
