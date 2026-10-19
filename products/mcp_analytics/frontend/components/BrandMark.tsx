import { type SVGProps } from 'react'

import { IconBrain, IconLaptop, IconLogomark, IconQuestion } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { BRAND_MARKS, type BrandMarkName, type IconMarkName } from '../brandMarks'

// The outline icons are filled shapes, not strokes, so a stroke in the fill color thickens their lines
// to sit closer to the solid brand marks around them.
function boldOutline(strokeWidth: number): SVGProps<SVGSVGElement> {
    return { stroke: 'currentColor', strokeWidth, strokeLinejoin: 'round' }
}

// @posthog/icons icons leave padding inside their 24x24 box and the brand marks do not, so the icons are
// scaled up to match. The PostHog mark is wide and short, so it needs more scale.
const ICON_MARKS: Record<
    IconMarkName,
    { Icon: typeof IconLogomark; className?: string; outline?: SVGProps<SVGSVGElement> }
> = {
    PostHog: { Icon: IconLogomark, className: 'scale-[1.18]' },
    'Unbranded model': { Icon: IconBrain, className: 'scale-110', outline: boldOutline(0.2) },
    'Other harnesses': { Icon: IconLaptop, className: 'scale-110', outline: boldOutline(0.15) },
    'Unidentified client': { Icon: IconQuestion },
}

function isIconMark(name: BrandMarkName): name is IconMarkName {
    return Object.prototype.hasOwnProperty.call(ICON_MARKS, name)
}

// Mark names from untrusted input, such as HogQL's withIcon(), must pass through here before reaching BrandMark.
export function toBrandMarkName(name: string): BrandMarkName {
    return Object.prototype.hasOwnProperty.call(ICON_MARKS, name) ||
        Object.prototype.hasOwnProperty.call(BRAND_MARKS, name)
        ? (name as BrandMarkName)
        : 'Other harnesses'
}

// Pass a label only when the mark stands alone. Next to a visible name, an unlabelled mark stays hidden
// from screen readers so they do not read the name twice. The title stays on the wrapper so the
// tooltip works for both kinds of mark.
export function BrandMark({
    name,
    label,
    className = 'size-4',
}: {
    name: BrandMarkName
    label?: string
    className?: string
}): JSX.Element {
    const a11y = label ? ({ role: 'img', 'aria-label': label } as const) : ({ 'aria-hidden': true } as const)
    let mark: JSX.Element
    if (isIconMark(name)) {
        const { Icon, className: iconClassName, outline } = ICON_MARKS[name]
        mark = <Icon className={cn('shrink-0', iconClassName, className)} {...a11y} {...outline} />
    } else {
        const shape = BRAND_MARKS[name]
        mark = (
            <svg
                {...a11y}
                viewBox="0 0 24 24"
                fill="currentColor"
                fillRule={'evenOdd' in shape ? 'evenodd' : undefined}
                className={cn('shrink-0', className)}
            >
                {shape.paths.map((d) => (
                    <path key={d} d={d} />
                ))}
            </svg>
        )
    }
    return (
        <span title={label} className="inline-flex shrink-0">
            {mark}
        </span>
    )
}
