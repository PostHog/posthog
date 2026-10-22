import { cn } from 'lib/utils/css-classes'

import type { StepFacts } from './stepFacts'

export const CAPTION_WIDTH = 230

// Facts quote step content such as property values and messages, so recordings must not capture them.
/** A tile and the panel head keep the caption short, so a long email subject cannot stretch them. The hover card shows more. */
const LINES = { tile: 'line-clamp-2', card: 'line-clamp-4' }

export function TileCaption({
    facts,
    name,
    size = 'tile',
}: {
    facts: StepFacts
    /** A name the author gave the step leads, and what the step does follows it. */
    name?: string
    size?: keyof typeof LINES
}): JSX.Element {
    if (name) {
        return (
            <div className="ph-no-capture flex w-57.5 flex-col gap-0.5 pt-1 text-left">
                <div className={cn('break-words text-[13px] font-semibold leading-tight', LINES[size])}>{name}</div>
                <div className={cn('break-words text-xs leading-snug text-secondary', LINES[size])}>
                    {facts.headline}
                </div>
            </div>
        )
    }
    return (
        <div className="ph-no-capture flex w-57.5 flex-col gap-0.5 pt-1 text-left">
            <div className={cn('break-words text-[13px] font-semibold leading-tight', LINES[size])}>
                {facts.headline}
            </div>
            {facts.detail && (
                <div className={cn('break-words text-xs leading-snug text-secondary', LINES[size])}>{facts.detail}</div>
            )}
        </div>
    )
}
