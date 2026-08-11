/**
 * Animated three-dot ellipsis used while the inbox is warming up.
 *
 * Faithful port of desktop's `inbox-ellipsis-dot` wave. Desktop drives it from a
 * global CSS class (`packages/ui/src/styles/globals.css`); cloud has no such class,
 * so we inline the same keyframe in a scoped <style> and stagger the three dots
 * (0 / 160 / 320ms) exactly as desktop does. The motion is a subtle 1px lift with
 * an opacity dip – intentionally gentler than Tailwind's `animate-bounce`.
 */
export function AnimatedEllipsis(): JSX.Element {
    return (
        <span aria-hidden className="inbox-ellipsis">
            {/* eslint-disable-next-line react/no-danger */}
            <style dangerouslySetInnerHTML={{ __html: ELLIPSIS_CSS }} />
            <span className="inline-flex items-end gap-px leading-none">
                <span className="inbox-ellipsis__dot">.</span>
                <span className="inbox-ellipsis__dot">.</span>
                <span className="inbox-ellipsis__dot">.</span>
            </span>
        </span>
    )
}

const ELLIPSIS_CSS = `
@keyframes inboxEllipsisWave {
    0%, 60%, 100% { opacity: 0.12; transform: translateY(0); }
    30% { opacity: 1; transform: translateY(-1px); }
}
.inbox-ellipsis__dot {
    display: inline-block;
    animation: inboxEllipsisWave 1.05s ease-in-out infinite;
}
.inbox-ellipsis__dot:nth-child(1) { animation-delay: 0ms; }
.inbox-ellipsis__dot:nth-child(2) { animation-delay: 160ms; }
.inbox-ellipsis__dot:nth-child(3) { animation-delay: 320ms; }
@media (prefers-reduced-motion: reduce) {
    .inbox-ellipsis__dot { animation: none; opacity: 0.6; }
}
`
