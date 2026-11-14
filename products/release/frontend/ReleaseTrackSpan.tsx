import { cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SPAN_LOOK, Scale, TONE_COLOR, x } from './releaseTracks'
import { ReleaseSpan } from './releaseUtils'

const NARROW = 72

export function ReleaseTrackSpan({
    span,
    scale,
    top,
    height,
    thin,
    stickyOffset = 0,
}: {
    span: ReleaseSpan
    scale: Scale
    top: number
    height: number
    thin?: boolean
    stickyOffset?: number
}): JSX.Element | null {
    const left = x(span.from, scale)
    const width = Math.max(x(span.to, scale) + scale.day / 2 - left, scale.day)
    if (dayjs(span.to).isBefore(scale.start, 'day')) {
        return null
    }
    const color = span.tone ? TONE_COLOR[span.tone] : SPAN_LOOK[span.kind].color
    const compact = thin || width < NARROW
    const cutLeft = dayjs(span.from).isBefore(scale.start, 'day')
    const cutRight = left + width >= scale.days * scale.day
    return (
        <div className="absolute flex" style={{ left, width, top, height }}>
            <div
                className={cn(
                    'flex w-full rounded-full',
                    compact ? 'my-auto h-1.5' : 'h-full',
                    cutLeft && 'rounded-l-none',
                    cutRight && 'rounded-r-none'
                )}
                style={{
                    clipPath: `inset(0 round ${cutLeft ? 0 : 9999}px ${cutRight ? 0 : 9999}px ${cutRight ? 0 : 9999}px ${cutLeft ? 0 : 9999}px)`,
                    backgroundColor: `color-mix(in oklab, ${color} ${compact ? 70 : 18}%, transparent)`,
                }}
            >
                <LinkPrimitive
                    to={span.href}
                    title={span.label}
                    className="flex w-full items-center px-2 text-[10px] font-medium text-foreground"
                >
                    {!compact && (
                        <span className="sticky truncate" style={{ left: stickyOffset + 8, maxWidth: width - 16 }}>
                            {span.label}
                        </span>
                    )}
                </LinkPrimitive>
            </div>
            {compact && !thin && span.label && (
                <span className="pointer-events-none absolute left-full top-1/2 ml-1.5 -translate-y-1/2 whitespace-nowrap text-[10px] font-medium text-muted-foreground">
                    {span.label}
                </span>
            )}
        </div>
    )
}
