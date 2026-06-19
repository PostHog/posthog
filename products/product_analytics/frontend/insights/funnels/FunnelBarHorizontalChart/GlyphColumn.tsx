import clsx from 'clsx'

import { IconInfinity } from '@posthog/icons'

import { SeriesGlyph } from 'lib/components/SeriesGlyph'

export const GLYPH_HEIGHT_PX = 23

interface GlyphColumnProps {
    /** Zero-based step index. */
    index: number
    stepCount: number
    /** Display number inside the glyph (usually `index + 1`). */
    glyphNumber: number
    isUnordered: boolean
    isOptional: boolean
    hasOptionalSteps: boolean
}

const LINE_CLASS = 'absolute left-[calc(50%-1px)] w-[2px] border-r-2 border-[var(--color-border-primary)] opacity-50'

export function GlyphColumn({
    index,
    stepCount,
    glyphNumber,
    isUnordered,
    isOptional,
    hasOptionalSteps,
}: GlyphColumnProps): JSX.Element {
    const halfGlyph = GLYPH_HEIGHT_PX / 2

    return (
        <div
            className={clsx(
                'relative flex flex-col items-center shrink-0',
                hasOptionalSteps ? 'w-16' : 'w-6',
                isOptional && 'opacity-70'
            )}
        >
            {index > 0 && (
                // eslint-disable-next-line react/forbid-dom-props
                <div className={LINE_CLASS} style={{ top: 0, height: halfGlyph }} />
            )}
            {isOptional && hasOptionalSteps && (
                <div className="absolute top-0 left-[calc(50%-1px)] w-[2px] h-full bg-[var(--color-border-primary)] opacity-50 z-[1]" />
            )}
            {isOptional && (
                <div className="absolute top-[calc(50%-1px)] left-[calc(50%-1px)] w-6 h-[2px] bg-[var(--color-border-primary)] opacity-50" />
            )}
            <div className={clsx('relative z-10 select-none', isOptional && 'ml-6')}>
                <SeriesGlyph variant="funnel-step-glyph">
                    {isUnordered ? <IconInfinity style={{ fill: 'var(--primary_alt)', width: 14 }} /> : glyphNumber}
                </SeriesGlyph>
            </div>
            {index < stepCount - 1 && (
                // eslint-disable-next-line react/forbid-dom-props
                <div className={LINE_CLASS} style={{ top: halfGlyph, bottom: 0 }} />
            )}
        </div>
    )
}
