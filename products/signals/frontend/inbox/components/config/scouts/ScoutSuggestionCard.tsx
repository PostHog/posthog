import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { ScoutSuggestionItemApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { suggestionCadenceLabel, suggestionMetaLine } from '../../../utils/scoutSuggestions'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'

/** How much of a drafted scout body the expanded card shows before pointing at the full draft. */
const DRAFT_PREVIEW_CHARS = 400

export interface ScoutSuggestionCardProps {
    item: ScoutSuggestionItemApi
    surface: ScoutSuggestionSurface
}

/**
 * One suggested scout: what it would watch, why it was picked for this project, and the three ways
 * to act on it. Clicking the body expands it in place, so reading the whole draft never leaves the
 * roster. Both kinds open the create form pre-filled: a custom pick with its draft, a canonical pick
 * with the scout that already exists, so the person reads it before turning it on.
 */
export function ScoutSuggestionCard({ item, surface }: ScoutSuggestionCardProps): JSX.Element {
    const { busySuggestionIds, expandedSuggestionId } = useValues(scoutSuggestionsLogic)
    const { dismissSuggestion, toggleSuggestionExpanded } = useActions(scoutSuggestionsLogic)
    const isBusy = busySuggestionIds.includes(item.id)
    const isExpanded = expandedSuggestionId === item.id

    return (
        <div className="relative flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3">
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
                onClick={() => toggleSuggestionExpanded(item, surface)}
                className="flex flex-col items-start gap-1.5 pr-6 text-left"
                aria-expanded={isExpanded}
                data-attr="scout-suggestion-body"
            >
                <SuggestionTags item={item} />
                <span className="text-sm font-semibold leading-snug">{item.title}</span>
                <p className={cn('m-0 text-xs leading-snug text-secondary', !isExpanded && 'line-clamp-2')}>
                    {item.why_here}
                </p>
            </button>
            {isExpanded && <SuggestionDetails item={item} />}
            {/* Pushed down so every card in a row puts its buttons on the same line, however many
                lines its evidence and cadence take. */}
            <span className="mt-auto pt-1 text-[11px] text-tertiary">{suggestionMetaLine(item.proposed_config)}</span>
            <SuggestionActions item={item} surface={surface} isBusy={isBusy} />
        </div>
    )
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
                type="primary"
                size="xsmall"
                loading={isBusy}
                disabledReason={isCanonical ? undefined : (creationDisabledReason ?? undefined)}
                onClick={() => openCreateFromSuggestion(item, surface)}
                data-attr={isCanonical ? 'scout-suggestion-turn-on' : 'scout-suggestion-create'}
            >
                {isCanonical ? 'Turn on' : 'Create scout'}
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

/** The rest of a suggestion, shown in place once the card is expanded. */
function SuggestionDetails({ item }: { item: ScoutSuggestionItemApi }): JSX.Element {
    const draftPreview = item.draft_body.slice(0, DRAFT_PREVIEW_CHARS)

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            {item.description && <p className="m-0 text-xs leading-snug text-secondary">{item.description}</p>}
            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-tertiary">Name</dt>
                <dd className="m-0 truncate font-mono text-[11px]">{item.skill_name}</dd>
                <dt className="text-tertiary">Schedule</dt>
                <dd className="m-0">Runs {suggestionCadenceLabel(item.proposed_config)}</dd>
                <dt className="text-tertiary">Output</dt>
                <dd className="m-0">
                    {item.proposed_config.emit ? 'Files reports to the inbox' : 'Dry run, files nothing'}
                </dd>
            </dl>
            {draftPreview && (
                <div className="flex flex-col gap-1">
                    <span className="text-[11px] text-tertiary">What it would do on every run</span>
                    <p className="m-0 whitespace-pre-wrap font-mono text-[11px] leading-snug text-secondary">
                        {draftPreview}
                        {item.draft_body.length > DRAFT_PREVIEW_CHARS && '…'}
                    </p>
                    {item.draft_body.length > DRAFT_PREVIEW_CHARS && (
                        <span className="text-[11px] text-tertiary">
                            Open Create scout to read and edit the whole draft.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
