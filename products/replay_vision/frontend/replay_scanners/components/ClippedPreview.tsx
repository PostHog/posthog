import { useState } from 'react'

import { LemonModal, Link } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'

// Tailwind needs literal class names, so each clip height pairs its class with the pixel value it measures against.
const CLIPS = {
    short: { className: 'max-h-20', px: 80 },
    tall: { className: 'max-h-60', px: 240 },
} as const

export function ClippedPreview({
    clip,
    modalTitle,
    buttonLabel,
    children,
    modalContent,
    onOpenFull,
    dataAttr,
}: {
    clip: keyof typeof CLIPS
    /** Title of the built-in modal. Unused with `onOpenFull`. */
    modalTitle?: string
    buttonLabel: string
    children: React.ReactNode
    modalContent?: React.ReactNode
    /** Opens the caller's own full view instead of this component's modal, for content that has a richer one. */
    onOpenFull?: () => void
    dataAttr: string
}): JSX.Element {
    const [open, setOpen] = useState(false)
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
                <Link
                    className="self-start text-xs"
                    onClick={() => (onOpenFull ? onOpenFull() : setOpen(true))}
                    data-attr={dataAttr}
                >
                    {buttonLabel}
                </Link>
            )}
            {!onOpenFull && (
                <LemonModal isOpen={open} onClose={() => setOpen(false)} title={modalTitle} width={720}>
                    {modalContent ?? children}
                </LemonModal>
            )}
        </div>
    )
}
