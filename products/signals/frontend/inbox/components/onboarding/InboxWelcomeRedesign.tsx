import './InboxWelcomeRedesign.scss'

import { useEffect, useRef, useState } from 'react'

import { IconRewindPlay, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { IconSlack } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { captureInboxWelcomeCommandCopied, captureInboxWelcomeViewed } from '../../inboxAnalytics'
import { SELF_DRIVING_WIZARD_COMMAND } from './InboxOnboarding'
import { ManualSetupAction } from './ManualSetupAction'

/** How long the copy button reads "Copied" before flipping back. */
const COPIED_RESET_MS = 1600

/**
 * The hero CTA: the wizard command on a near-black block with a single yellow copy button.
 * The button is its own feedback ("Copy" -> "Copied"), so the clipboard toast is suppressed.
 */
function CommandCta(): JSX.Element {
    const [copied, setCopied] = useState(false)
    const resetTimerRef = useRef<number | null>(null)

    useEffect(() => {
        return () => {
            if (resetTimerRef.current !== null) {
                window.clearTimeout(resetTimerRef.current)
            }
        }
    }, [])

    const handleCopy = (): void => {
        void copyToClipboard(SELF_DRIVING_WIZARD_COMMAND, 'self-driving setup command', { silent: true })
        captureInboxWelcomeCommandCopied({ variant: 'redesign', surface: 'takeover' })
        setCopied(true)
        if (resetTimerRef.current !== null) {
            window.clearTimeout(resetTimerRef.current)
        }
        resetTimerRef.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
    }

    return (
        <div className="InboxWelcomeRedesign__cta flex flex-wrap items-center justify-center gap-x-3 gap-y-2.5 py-2.5 pl-4 pr-2.5">
            <span className="whitespace-nowrap font-mono text-sm text-white">
                <span className="select-none text-[#6f6f76]">$ </span>
                {SELF_DRIVING_WIZARD_COMMAND}
            </span>
            <button
                type="button"
                className="InboxWelcomeRedesign__copy-button"
                onClick={handleCopy}
                aria-label="Copy self-driving setup command"
            >
                {copied ? 'Copied' : 'Copy'}
            </button>
        </div>
    )
}

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
            className={`InboxWelcomeRedesign__stage InboxWelcomeRedesign__stage--${stage} ${className ?? ''}`}
        >
            {children}
        </LemonCard>
    )
}

function Arrow({ second = false }: { second?: boolean }): JSX.Element {
    return (
        <div
            className={`InboxWelcomeRedesign__arrow ${
                second ? 'InboxWelcomeRedesign__arrow--second ' : ''
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
function LoopDiagram(): JSX.Element {
    return (
        <div className="pointer-events-none select-none grid grid-cols-1 items-center gap-x-1.5 gap-y-4 md:grid-cols-[1fr_34px_1fr_34px_1.2fr]">
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
                    <div className="flex items-center gap-2 text-[13px] font-semibold">
                        <span className="size-[7px] shrink-0 rounded-full bg-success" />
                        Reproduced the bug, wrote the fix
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

/**
 * Redesigned self-driving welcome takeover (test arm of the `inbox-welcome-redesign` experiment;
 * `InboxOnboardingTakeover` is control). Leads with the payoff, makes the wizard command the one
 * CTA, and explains signal sources and the scouts & pipeline stage as labels over an animated loop instead of prose.
 * Rendered without the tab bar: this variant is a full-pane welcome, not a locked tab.
 */
export function InboxWelcomeRedesign(): JSX.Element {
    useEffect(() => {
        captureInboxWelcomeViewed({ variant: 'redesign' })
    }, [])

    return (
        <div className="InboxWelcomeRedesign flex min-h-full flex-col justify-center py-10">
            <div className="px-6 pb-12">
                <div className="mx-auto flex max-w-[720px] flex-col items-center text-center">
                    <div className="mb-7">
                        <Logomark jumpOnClick size="xl" />
                    </div>
                    <h1 className="mb-4 text-2xl font-bold leading-[1.1] tracking-[-0.02em] sm:text-[32px]">
                        Ship fixes while you sleep
                    </h1>
                    <p className="mb-9 max-w-[560px] text-[15px] leading-[1.55] text-secondary">
                        PostHog watches your session replays, errors, and Slack. When it finds something worth fixing,
                        it writes the pull request. You review and merge.
                    </p>
                    <CommandCta />
                    <p className="mt-3.5 max-w-[520px] text-[13px] text-tertiary">
                        Run it in your repo. That's the whole setup: it connects GitHub and picks the signal sources and
                        scouts to watch. PRs start landing in this inbox.
                    </p>
                    <ManualSetupAction variant="redesign" className="mt-7 items-center text-center" />
                </div>
            </div>
            <div className="px-6 md:px-12">
                <div className="mx-auto max-w-[1060px]">
                    <LoopDiagram />
                    <p className="mt-6 text-center text-xs text-tertiary">
                        Your first 3 PRs each month are free, then $15 per PR. Reports are always free.
                    </p>
                </div>
            </div>
        </div>
    )
}
