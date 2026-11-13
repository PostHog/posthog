import { Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { Lane, laneHeight, statusLabel } from './releaseTracks'

const LANE_ICON: Record<Lane['kind'], string> = {
    flag: 'feature_flag',
    experiment: 'experiment',
    early_access: 'early_access_feature',
    broadcast: 'broadcasts',
}

function laneDetail(lane: Lane): string {
    if (lane.kind !== 'flag') {
        return statusLabel(lane.status)
    }
    const { audience } = lane
    const parts = [
        lane.flag.active ? null : 'Disabled',
        audience ? (audience.percent !== null ? `${audience.who} · ${audience.percent}%` : audience.summary) : null,
        audience?.variants.length
            ? audience.variants.map((variant) => `${variant.key} ${variant.percent}%`).join(', ')
            : null,
    ]
    return parts.filter(Boolean).join(' · ')
}

export function ReleaseTrackLabel({
    lane,
    className,
    detailed,
    actions,
}: {
    lane: Lane
    className?: string
    detailed?: boolean
    actions?: JSX.Element
}): JSX.Element {
    const detail = detailed ? laneDetail(lane) : ''
    return (
        <div className={cn('flex items-center gap-2', className)} style={{ height: laneHeight(lane, detailed) }}>
            <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-3.5">
                {iconForType(LANE_ICON[lane.kind] as never)}
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <LinkPrimitive
                    to={lane.href}
                    className={cn(
                        'truncate text-foreground hover:underline',
                        lane.kind === 'flag' ? 'font-mono text-[11px]' : 'text-xs'
                    )}
                >
                    {lane.title}
                </LinkPrimitive>
                {detail && (
                    <Text size="xxs" variant="muted" className="truncate" title={detail}>
                        {detail}
                    </Text>
                )}
            </span>
            {!detailed && !lane.live && (
                <Text size="xs" variant="muted" className="shrink-0">
                    {statusLabel(lane.status)}
                </Text>
            )}
            {actions && (
                <span className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/track:opacity-100">
                    {actions}
                </span>
            )}
        </div>
    )
}
