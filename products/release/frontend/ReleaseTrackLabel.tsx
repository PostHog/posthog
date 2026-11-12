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

export function ReleaseTrackLabel({ lane, className }: { lane: Lane; className?: string }): JSX.Element {
    return (
        <div className={cn('flex items-center gap-2', className)} style={{ height: laneHeight(lane) }}>
            <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-3.5">
                {iconForType(LANE_ICON[lane.kind] as never)}
            </span>
            <LinkPrimitive
                to={lane.href}
                className={cn(
                    'min-w-0 flex-1 truncate text-foreground hover:underline',
                    lane.kind === 'flag' ? 'font-mono text-[11px]' : 'text-xs'
                )}
            >
                {lane.title}
            </LinkPrimitive>
            {!lane.live && (
                <Text size="xs" variant="muted" className="shrink-0">
                    {statusLabel(lane.status)}
                </Text>
            )}
        </div>
    )
}
