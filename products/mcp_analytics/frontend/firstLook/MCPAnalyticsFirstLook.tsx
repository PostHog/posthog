import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconBolt, IconChevronDown, IconChevronRight, IconClock, IconSparkles, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Link } from 'lib/lemon-ui/Link/Link'
import posthog from 'lib/posthog-typed'
import { cn } from 'lib/utils/css-classes'

import { harnessLogo } from '../dashboard/harnessRegistry'
import type { FirstLookChip } from './firstLookCopy'
import { mcpFirstLookLogic } from './mcpFirstLookLogic'

const CHIP_ICON: Record<string, JSX.Element> = {
    'top-tool': <IconBolt />,
    'worst-error': <IconWarning />,
    p95: <IconClock />,
    // Fallback for the client chip when the harness has no logo (e.g. "Other").
    client: <IconSparkles />,
}

function Chip({ chip }: { chip: FirstLookChip }): JSX.Element {
    const logo = chip.harness ? harnessLogo(chip.harness) : undefined
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1.5 rounded-full bg-surface-secondary px-2.5 py-1 text-xs',
                chip.tone === 'danger' ? 'text-danger' : 'text-secondary'
            )}
        >
            <span className="flex items-center text-xs leading-none">
                {logo ? <img src={logo.src} alt={logo.alt} className="size-3.5" /> : CHIP_ICON[chip.key]}
            </span>
            <span className="text-muted">{chip.label}</span>
            <span className="font-medium text-primary">{chip.value}</span>
        </span>
    )
}

/**
 * Personalized "first look" shown once when a project's first MCP tool calls land — turns the
 * bare dashboard into "here's what we already see" plus two ways to dig deeper. Self-gates via
 * `shouldShow`; renders `null` otherwise.
 */
export function MCPAnalyticsFirstLook(): JSX.Element | null {
    const { shouldShow, headline, chips, editorPrompt, editorExpanded, eventProperties } = useValues(mcpFirstLookLogic)
    const { dismiss, dismissAndAskMax, toggleEditor } = useActions(mcpFirstLookLogic)

    // Fire once when the card first becomes visible — for replay filtering + impact.
    const shownRef = useRef(false)
    useEffect(() => {
        if (shouldShow && !shownRef.current) {
            shownRef.current = true
            posthog.captureRaw('mcp analytics first look shown', eventProperties)
        }
    }, [shouldShow, eventProperties])

    if (!shouldShow) {
        return null
    }

    return (
        <LemonCard
            hoverEffect={false}
            closeable
            onClose={dismiss}
            className="bg-gradient-to-br from-accent/15 via-accent/5 to-surface-primary"
        >
            <div className="flex flex-col gap-4 pr-6">
                <div className="flex items-center gap-2 text-accent">
                    <IconSparkles className="text-lg" />
                    <span className="text-xs font-semibold uppercase tracking-wide">Your first look</span>
                </div>
                <h2 className="m-0 text-lg font-semibold text-primary">{headline}</h2>
                {chips.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {chips.map((chip) => (
                            <Chip key={chip.key} chip={chip} />
                        ))}
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton type="primary" icon={<IconSparkles />} onClick={dismissAndAskMax}>
                        Ask PostHog AI
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={editorExpanded ? <IconChevronDown /> : <IconChevronRight />}
                        onClick={toggleEditor}
                        data-attr="mcp-first-look-editor-toggle"
                    >
                        Prefer your editor?
                    </LemonButton>
                </div>
                {editorExpanded && (
                    <div className="flex flex-col gap-2 rounded border border-border bg-surface-primary p-3">
                        <p className="m-0 text-xs text-muted">
                            {editorPrompt.label}, or any agent with the PostHog MCP installed:
                        </p>
                        <div className="flex items-start gap-2 rounded bg-surface-secondary px-2.5 py-1.5">
                            <span className="flex-1 font-mono text-xs text-primary">{editorPrompt.prompt}</span>
                            <CopyToClipboardInline
                                explicitValue={editorPrompt.prompt}
                                description="prompt"
                                iconSize="small"
                            />
                        </div>
                        <p className="m-0 text-xs text-muted">
                            Needs the PostHog MCP in your editor.{' '}
                            <Link to="https://posthog.com/docs/model-context-protocol" target="_blank">
                                Set it up
                            </Link>
                        </p>
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
