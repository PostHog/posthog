import { Link } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'

// Tailwind needs literal class names, so each clip height pairs its class with the pixel value it measures against.
const CLIPS = {
    short: { className: 'max-h-20', px: 80 },
    tall: { className: 'max-h-60', px: 240 },
} as const

export function ClippedPreview({
    clip,
    buttonLabel,
    children,
    onOpenFull,
    dataAttr,
}: {
    clip: keyof typeof CLIPS
    buttonLabel: string
    children: React.ReactNode
    onOpenFull: () => void
    dataAttr: string
}): JSX.Element {
    const { ref, height } = useResizeObserver()
    const { className, px } = CLIPS[clip]
    const overflows = (height ?? 0) > px

    return (
        <div className="flex flex-col gap-1">
            <div
                className={`${className} overflow-hidden ${
                    overflows ? '[mask-image:linear-gradient(to_bottom,black_60%,transparent)]' : ''
                }`}
            >
                {/* Measured unclipped (the parent's overflow doesn't shrink it), so the button shows only when there's more. */}
                <div ref={ref}>{children}</div>
            </div>
            {overflows && (
                <Link className="self-start text-xs" onClick={onOpenFull} data-attr={dataAttr}>
                    {buttonLabel}
                </Link>
            )}
        </div>
    )
}
