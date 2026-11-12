import { cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SPAN_LOOK, Scale, TONE_COLOR, x } from './releaseTracks'
import { ReleaseSpan } from './releaseUtils'

const NARROW = 72

export function ReleaseTrackSpan({
    span,
    scale,
    top,
    height,
}: {
    span: ReleaseSpan
    scale: Scale
    top: number
    height: number
}): JSX.Element | null {
    const left = x(span.from, scale)
    const width = Math.max(x(span.to, scale) + scale.day / 2 - left, scale.day)
    if (x(span.to, scale) === 0) {
        return null
    }
    const color = span.tone ? TONE_COLOR[span.tone] : SPAN_LOOK[span.kind].color
    return (
        <div className="absolute flex" style={{ left, width, top, height }}>
            <div
                className={cn('flex w-full overflow-hidden rounded-full', width < NARROW ? 'my-auto h-1.5' : 'h-full')}
                style={{
                    backgroundColor: `color-mix(in oklab, ${color} ${width < NARROW ? 70 : 18}%, transparent)`,
                }}
            >
                <LinkPrimitive
                    to={span.href}
                    title={span.label}
                    className="flex w-full items-center px-2 text-[10px] font-medium text-foreground"
                >
                    {width >= NARROW && <span className="truncate">{span.label}</span>}
                </LinkPrimitive>
            </div>
            {width < NARROW && span.label && (
                <span className="pointer-events-none absolute left-full top-1/2 ml-1.5 -translate-y-1/2 whitespace-nowrap text-[10px] font-medium text-muted-foreground">
                    {span.label}
                </span>
            )}
        </div>
    )
}
