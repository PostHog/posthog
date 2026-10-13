// The stage/arrow animation classes live in InboxWelcome.scss, imported here too so the
// diagram animates wherever it renders (the welcome takeover and the intro modal).
import './InboxWelcome.scss'

import { IconRewindPlay, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'

function StageLabel({ children }: { children: string }): JSX.Element {
    return <div className="text-center text-xs font-semibold text-secondary">{children}</div>
}

/** A card in the loop diagram, lighting up at its stage's moment in the 9s sequence. */
function StageCard({
    stage,
    className,
    children,
}: {
    stage: 'signals' | 'pipeline' | 'inbox'
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className={`InboxWelcome__stage InboxWelcome__stage--${stage} ${className ?? ''}`}
        >
            {children}
        </LemonCard>
    )
}

function Arrow({ second = false }: { second?: boolean }): JSX.Element {
    return (
        <div
            className={`InboxWelcome__arrow ${
                second ? 'InboxWelcome__arrow--second ' : ''
            }hidden pt-5 text-center text-2xl text-border-secondary md:block`}
            aria-hidden="true"
        >
            &#8594;
        </div>
    )
}

/**
 * The illustrative loop: signal sources -> scouts & pipeline -> a PR in your inbox. Never interactive
 * (pointer-events-none on the whole grid); the cards and the Review button are props, not UI.
 */
export function LoopDiagram(): JSX.Element {
    return (
        // text-left so the mock UI stays left-aligned even inside a text-center hero (the intro modal)
        <div className="pointer-events-none select-none grid grid-cols-1 items-center gap-x-1.5 gap-y-4 text-left md:grid-cols-[1fr_34px_1fr_34px_1.2fr]">
            <div className="flex flex-col gap-2">
                <StageLabel>Signal sources</StageLabel>
                <StageCard stage="signals" className="flex items-center gap-2 px-3 py-2.5">
                    <span className="flex size-5 shrink-0 items-center justify-center">
                        <IconRewindPlay className="text-sm text-[var(--color-product-session-replay-light)] dark:text-[var(--color-product-session-replay-dark)]" />
                    </span>
                    <span className="truncate text-xs">Rage clicks in checkout replay</span>
                </StageCard>
                <StageCard stage="signals" className="flex items-center gap-2 px-3 py-2.5">
                    <span className="flex size-5 shrink-0 items-center justify-center">
                        <IconWarning className="text-sm text-[var(--color-product-error-tracking-light)] dark:text-[var(--color-product-error-tracking-dark)]" />
                    </span>
                    <span className="truncate font-mono text-xs">TypeError in checkout</span>
                </StageCard>
                <StageCard stage="signals" className="flex items-center gap-2 px-3 py-2.5">
                    <span className="flex size-5 shrink-0 items-center justify-center">
                        <IconSlack className="size-4" />
                    </span>
                    <span className="truncate text-xs">"checkout hangs on Safari"</span>
                </StageCard>
            </div>
            <Arrow />
            <div className="flex flex-col gap-2">
                <StageLabel>Scouts &amp; pipeline</StageLabel>
                <StageCard stage="pipeline" className="flex flex-col gap-1.5 px-3.5 py-3">
                    {/* items-start + margin keeps the dot on the first line when the text wraps
                        in narrower hosts (the intro modal) instead of floating between lines */}
                    <div className="flex items-start gap-2 text-[13px] font-semibold">
                        <span className="mt-1.5 size-[7px] shrink-0 rounded-full bg-success" />
                        <span className="min-w-0">Reproduced the bug, wrote the fix</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-success">+142</span>
                        <span className="font-mono text-xs font-semibold text-danger">&minus;38</span>
                        <LemonTag type="success">Tests passing</LemonTag>
                    </div>
                </StageCard>
            </div>
            <Arrow second />
            <div className="flex flex-col gap-2">
                <StageLabel>Your inbox</StageLabel>
                <StageCard stage="inbox" className="flex items-center gap-2.5 px-3.5 py-3">
                    <span className="flex size-[26px] shrink-0 items-center justify-center rounded-md bg-fill-warning-highlight font-mono text-[11px] font-bold text-warning">
                        P1
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <div className="text-[13px] font-semibold">
                            <code>fix(checkout)</code> restore Safari encode
                        </div>
                        <div className="text-[11.5px] text-tertiary">#486 &middot; ready to merge</div>
                    </div>
                    <LemonButton type="primary" size="small" className="shrink-0">
                        Review
                    </LemonButton>
                </StageCard>
            </div>
        </div>
    )
}
