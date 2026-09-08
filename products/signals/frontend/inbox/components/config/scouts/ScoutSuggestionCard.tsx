import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

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
 * One suggested scout: what it would watch, why it was picked for this project, and the three ways
 * to act on it. The card carries the motivation only, because the create form already holds the
 * draft, the schedule and the output setting, and is where editing happens. Pressing the body opens
 * that form, so a person reads the offer before anything is written.
 */
export function ScoutSuggestionCard({ item, surface }: ScoutSuggestionCardProps): JSX.Element {
    const { busySuggestionIds } = useValues(scoutSuggestionsLogic)
    const { dismissSuggestion, openCreateFromSuggestion } = useActions(scoutSuggestionsLogic)
    const isBusy = busySuggestionIds.includes(item.id)
    // A canonical pick only turns a scout on, so the editor gate stops the draft path alone. The
    // busy guard stops both, because a repeat read can put the form back after the person closes it.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const bodyDisabled = isBusy || (item.kind !== 'canonical' && creationDisabledReason !== null)

    return (
        <div
            className={cn(
                'relative flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3',
                !bodyDisabled && 'transition-colors hover:border-secondary'
            )}
        >
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip="Dismiss. This won't be suggested again."
                disabledReason={isBusy ? 'Working on this suggestion' : undefined}
                onClick={() => dismissSuggestion(item, surface)}
                className="absolute right-1 top-1"
                aria-label={`Dismiss ${item.title}`}
                data-attr="scout-suggestion-dismiss"
            />
            <button
                type="button"
                disabled={bodyDisabled}
                onClick={() => openCreateFromSuggestion(item, surface, 'card')}
                className={cn('flex flex-col items-start gap-1.5 pr-6 text-left', !bodyDisabled && 'cursor-pointer')}
                // A name built from the children would lead with the "Turn on" tag and then read the
                // whole motivation, for a press that only opens the form.
                aria-label={`${reviewActionLabel(item)}: ${item.title}`}
                data-attr="scout-suggestion-body"
            >
                <SuggestionTags item={item} />
                <span className="text-sm font-semibold leading-snug">{item.title}</span>
                <p className="m-0 text-xs leading-snug text-secondary">{item.why_here}</p>
            </button>
            {/* Pushed down so every card in a row puts its buttons on the same line, however many
                lines its evidence and cadence take. */}
            <span className="mt-auto pt-1 text-[11px] text-tertiary">{suggestionMetaLine(item.proposed_config)}</span>
            <SuggestionActions item={item} surface={surface} isBusy={isBusy} />
        </div>
    )
}

/** What pressing the card does, carried by both the action button and the card body itself. */
function reviewActionLabel(item: ScoutSuggestionItemApi): string {
    return item.kind === 'canonical' ? 'Review scout' : 'Review draft'
}

/** What kind of offer the card makes, and how sure the producer was. */
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
            <span className="text-[11px] text-muted">{item.confidence} confidence</span>
        </div>
    )
}

/** The card's primary action, which depends on its kind, next to the chat that refines it. */
function SuggestionActions({ item, surface, isBusy }: ScoutSuggestionCardProps & { isBusy: boolean }): JSX.Element {
    const { aiConsentDisabledReason, runningChatType } = useValues(scoutSuggestionsLogic)
    const { refineSuggestionWithAi, openCreateFromSuggestion } = useActions(scoutSuggestionsLogic)
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
        <div className="flex flex-wrap items-center gap-1.5">
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={isBusy}
                disabledReason={isCanonical ? undefined : (creationDisabledReason ?? undefined)}
                onClick={() => openCreateFromSuggestion(item, surface)}
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
        </div>
    )
}
