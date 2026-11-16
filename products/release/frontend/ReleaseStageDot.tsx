import { cn } from '@posthog/quill'

import { ReleaseStage, STAGE_COLOR } from './releaseUtils'

export function ReleaseStageDot({ stage, className }: { stage: ReleaseStage; className?: string }): JSX.Element {
    const hollow = stage === 'planned'
    return (
        <span
            aria-hidden
            className={cn('inline-block size-2 shrink-0 rounded-full', hollow && 'border-[1.5px]', className)}
            style={hollow ? { borderColor: STAGE_COLOR[stage] } : { backgroundColor: STAGE_COLOR[stage] }}
        />
    )
}
