import { cn } from '@posthog/quill'

import { TodaySessionIcon } from '~/layout/today/TodaySessionIcon'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

export function SpaceFeedStatusIcon({ item, className }: { item: TodayWorkItem; className?: string }): JSX.Element {
    return (
        <span className={cn('flex size-3.5 shrink-0 items-center justify-center', className)}>
            <TodaySessionIcon item={item} />
        </span>
    )
}
