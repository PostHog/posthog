import { useActions, useValues } from 'kea'
import { useLayoutEffect, useRef, useState } from 'react'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { ScoutSuggestionItemApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { suggestionMetaLine } from '../../../utils/scoutSuggestions'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'

export interface ScoutSuggestionCardProps {
    item: ScoutSuggestionItemApi
    surface: ScoutSuggestionSurface
}

/**
 * One suggested scout as a row: what it would watch, why it was picked for this project, and the
 * three ways to act on it. The row carries the motivation only, because the create form already
 * holds the draft, the schedule and the output setting, and is where editing happens. Pressing the
 * body opens that form, so a person reads the offer before anything is written.
 */
export function ScoutSuggestionCard({ item, surface }: ScoutSuggestionCardProps): JSX.Element {
    const { busySuggestionIds } = useValues(scoutSuggestionsLogic)
    const { openCreateFromSuggestion } = useActions(scoutSuggestionsLogic)
    const isBusy = busySuggestionIds.includes(item.id)
    // A canonical pick only turns a scout on, so the editor gate stops the draft path alone. The
    // busy guard stops both, because a repeat read can put the form back after the person closes it.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const bodyDisabled = isBusy || (item.kind !== 'canonical' && creationDisabledReason !== null)

    const [expanded, setExpanded] = useState(false)
    const [overflowing, setOverflowing] = useState(false)
    const motivationRef = useRef<HTMLParagraphElement>(null)
    const motivationId = `scout-suggestion-motivation-${item.id}`

    useLayoutEffect(() => {
        const element = motivationRef.current
        if (expanded || !element) {
            return
        }
        const checkOverflow = (): void => setOverflowing(element.scrollHeight > element.clientHeight + 1)
        checkOverflow()
        const observer = new ResizeObserver(checkOverflow)
        observer.observe(element)
        return () => observer.disconnect()
    }, [item.why_here, expanded])

    return (
        <div
            className={cn(
                'flex flex-col gap-2 px-3 py-2.5 @2xl:flex-row @2xl:items-start @2xl:gap-4',
                !bodyDisabled && 'transition-colors hover:bg-surface-secondary'
            )}
        >
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
                <button
                    type="button"
                    disabled={bodyDisabled}
                    onClick={() => openCreateFromSuggestion(item, surface, 'card')}
                    className={cn(
                        'flex max-w-full flex-col items-start gap-1 text-left',
                        !bodyDisabled && 'cursor-pointer'
                    )}
                    // A name built from the children would lead with the "Turn on" tag and then read the
                    // whole motivation, for a press that only opens the form.
                    aria-label={`${reviewActionLabel(item)}: ${item.title}`}
                    data-attr="scout-suggestion-body"
                >
                    <div className="flex max-w-full flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="min-w-0 truncate text-sm font-semibold leading-snug">{item.title}</span>
                        <SuggestionTags item={item} />
                    </div>
                    <p
                        ref={motivationRef}
                        id={motivationId}
                        className={cn('m-0 text-xs leading-snug text-secondary', !expanded && 'line-clamp-2')}
                    >
                        {item.why_here}
                    </p>
                </button>
                <div className="flex flex-wrap items-center gap-x-2 text-[11px]">
                    <span className="text-tertiary">{suggestionMetaLine(item.proposed_config)}</span>
                    {/* Outside the row button, so keyboard and touch users can read the full motivation. */}
                    {(overflowing || expanded) && (
                        <Link
                            onClick={() => setExpanded(!expanded)}
                            aria-expanded={expanded}
                            aria-controls={motivationId}
                            data-attr="scout-suggestion-motivation-toggle"
                        >
                            {expanded ? 'Show less' : 'Show more'}
                        </Link>
                    )}
                </div>
            </div>
            <SuggestionActions item={item} surface={surface} isBusy={isBusy} />
        </div>
    )
}

/** What pressing the row does, carried by both the action button and the row body itself. */
function reviewActionLabel(item: ScoutSuggestionItemApi): string {
    return item.kind === 'canonical' ? 'Review scout' : 'Review draft'
}

/** What kind of offer the row makes, and how sure the producer was. */
function SuggestionTags({ item }: { item: ScoutSuggestionItemApi }): JSX.Element {
    const isCanonical = item.kind === 'canonical'
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <LemonTag type={isCanonical ? 'completion' : 'option'} size="small">
                {isCanonical ? 'Turn on' : 'New draft'}
            </LemonTag>
            {item.gap && (
                <Tooltip title="Nothing in your current fleet covers this.">
                    <LemonTag type="highlight" size="small">
                        Gap
                    </LemonTag>
                </Tooltip>
            )}
            <LemonTag type="muted" size="small">
                {capitalizeFirstLetter(item.confidence)} confidence
            </LemonTag>
        </div>
    )
}

/** The row's primary action, which depends on its kind, the chat that refines it, and dismiss. */
function SuggestionActions({ item, surface, isBusy }: ScoutSuggestionCardProps & { isBusy: boolean }): JSX.Element {
    const { aiConsentDisabledReason, runningChatType } = useValues(scoutSuggestionsLogic)
    const { refineSuggestionWithAi, openCreateFromSuggestion, dismissSuggestion } = useActions(scoutSuggestionsLogic)
    // A canonical pick opens the same form on the scout that already exists, so the person reads it
    // before it runs, and submitting only writes the config. Creating a draft and refining with AI
    // both end in a skill write, so those two carry the editor gate.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const chatDisabledReason = isBusy
        ? 'Starting a task…'
        : runningChatType !== null
          ? 'Starting another task…'
          : (creationDisabledReason ?? aiConsentDisabledReason ?? undefined)
    const isCanonical = item.kind === 'canonical'

    return (
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={isBusy}
                disabledReason={isCanonical ? undefined : (creationDisabledReason ?? undefined)}
                onClick={() => openCreateFromSuggestion(item, surface)}
                // One width for both labels, so the group starts at the same x on every row.
                className="min-w-24 justify-center"
                data-attr={isCanonical ? 'scout-suggestion-turn-on' : 'scout-suggestion-create'}
            >
                {reviewActionLabel(item)}
            </LemonButton>
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconSparkles />}
                disabledReason={chatDisabledReason}
                onClick={() => refineSuggestionWithAi(item, surface)}
                data-attr="scout-suggestion-refine"
            >
                Refine with AI
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip="Dismiss. This won't be suggested again."
                disabledReason={isBusy ? 'Working on this suggestion' : undefined}
                onClick={() => dismissSuggestion(item, surface)}
                aria-label={`Dismiss ${item.title}`}
                data-attr="scout-suggestion-dismiss"
            />
        </div>
    )
}
