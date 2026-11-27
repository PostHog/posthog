import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

import type { ScoutSuggestionItemApi } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutSuggestionDisclosureOpened, type ScoutSuggestionSurface } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { suggestionGoal, suggestionMetaLine } from '../../../utils/scoutSuggestions'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'

export interface ScoutSuggestionCardProps {
    item: ScoutSuggestionItemApi
    surface: ScoutSuggestionSurface
}

/**
 * The row carries a title, one sentence on what the scout does, and one action. The evidence folds
 * behind "Why this?", because a person new to scouts reads the goal first and the reasons only if
 * they doubt it. The create form already holds the draft, the schedule and the output setting, and
 * is where editing happens, so pressing the title or Review opens it before anything is written.
 */
export function ScoutSuggestionCard({ item, surface }: ScoutSuggestionCardProps): JSX.Element {
    const { busySuggestionIds } = useValues(scoutSuggestionsLogic)
    const { openCreateFromSuggestion } = useActions(scoutSuggestionsLogic)
    const isBusy = busySuggestionIds.includes(item.id)
    // A canonical pick only turns a scout on, so the editor gate stops the draft path alone. The
    // busy guard stops both, because a repeat read can put the form back after the person closes it.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const bodyDisabled = isBusy || (item.kind !== 'canonical' && creationDisabledReason !== null)

    const [motivationOpen, setMotivationOpen] = useState(false)
    const motivationId = `scout-suggestion-motivation-${item.id}`

    const toggleMotivation = (): void => {
        if (!motivationOpen) {
            captureScoutSuggestionDisclosureOpened({
                disclosure: 'why_this',
                surface,
                suggestion: { id: item.id, kind: item.kind, skillName: item.skill_name },
            })
        }
        setMotivationOpen(!motivationOpen)
    }

    return (
        <div
            className={cn(
                'flex flex-col gap-2 py-2.5 @2xl:flex-row @2xl:items-start @2xl:gap-4',
                surface === 'onboarding' ? 'px-0' : 'px-3',
                !bodyDisabled && 'transition-colors hover:bg-surface-secondary'
            )}
        >
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
                <button
                    type="button"
                    disabled={bodyDisabled}
                    onClick={() => openCreateFromSuggestion(item, surface, 'card')}
                    className={cn(
                        'max-w-full text-left text-sm font-semibold leading-snug break-words',
                        !bodyDisabled && 'cursor-pointer'
                    )}
                    // The visible text is only the title, so the name also says what the press does.
                    aria-label={`${reviewActionLabel(item)}: ${item.title}`}
                    data-attr="scout-suggestion-body"
                >
                    {item.title}
                </button>
                {/* The goal and the evidence render outside the row button, because both can hold links and
                    a link inside a button is not valid HTML. */}
                <LemonMarkdown className="max-w-full text-xs leading-snug text-secondary" disableImages>
                    {suggestionGoal(item)}
                </LemonMarkdown>
                <div className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-tertiary">
                    <span>{suggestionMetaLine(item.proposed_config)}</span>
                    <span aria-hidden>·</span>
                    <Link
                        onClick={toggleMotivation}
                        aria-expanded={motivationOpen}
                        aria-controls={motivationId}
                        data-attr="scout-suggestion-motivation-toggle"
                    >
                        {motivationOpen ? 'Hide reason' : 'Why this?'}
                    </Link>
                </div>
                <div id={motivationId} hidden={!motivationOpen} className="max-w-full border-l-2 border-primary pl-2">
                    <LemonMarkdown className="text-xs leading-snug text-secondary" disableImages>
                        {item.why_here}
                    </LemonMarkdown>
                </div>
            </div>
            <SuggestionActions item={item} surface={surface} isBusy={isBusy} />
        </div>
    )
}

/** What pressing the row does, carried by both the Review button and the row title itself. */
function reviewActionLabel(item: ScoutSuggestionItemApi): string {
    return item.kind === 'canonical' ? 'Review scout' : 'Review draft'
}

/** Review, plus a menu that holds the chat that refines the pick and the dismiss. */
function SuggestionActions({ item, surface, isBusy }: ScoutSuggestionCardProps & { isBusy: boolean }): JSX.Element {
    const { scoutChatDisabledReason, runningChatType } = useValues(scoutSuggestionsLogic)
    const { refineSuggestionWithAi, openCreateFromSuggestion, dismissSuggestion } = useActions(scoutSuggestionsLogic)
    // A canonical pick opens the same form on the scout that already exists, so the person reads it
    // before it runs, and submitting only writes the config. Creating a draft and refining with AI
    // both end in a skill write, so those two carry the editor gate.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const chatDisabledReason = isBusy
        ? 'Starting a task…'
        : runningChatType !== null
          ? 'Starting another task…'
          : (creationDisabledReason ?? scoutChatDisabledReason ?? undefined)
    const isCanonical = item.kind === 'canonical'

    return (
        <div className="flex shrink-0 items-center gap-1.5">
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={isBusy}
                disabledReason={isCanonical ? undefined : (creationDisabledReason ?? undefined)}
                onClick={() => openCreateFromSuggestion(item, surface)}
                className="min-w-20 justify-center"
                aria-label={reviewActionLabel(item)}
                data-attr={isCanonical ? 'scout-suggestion-turn-on' : 'scout-suggestion-create'}
            >
                Review
            </LemonButton>
            <LemonMenu
                placement="bottom-end"
                items={[
                    {
                        label: 'Refine with AI',
                        icon: <IconSparkles />,
                        disabledReason: chatDisabledReason,
                        onClick: () => refineSuggestionWithAi(item, surface),
                        'data-attr': 'scout-suggestion-refine',
                    },
                    surface !== 'onboarding' && {
                        label: 'Not interested',
                        icon: <IconX />,
                        tooltip: "This won't be suggested again.",
                        disabledReason: isBusy ? 'Working on this suggestion' : undefined,
                        onClick: () => dismissSuggestion(item, surface),
                        'data-attr': 'scout-suggestion-dismiss',
                    },
                ]}
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconEllipsis />}
                    aria-label={`More options for ${item.title}`}
                    data-attr="scout-suggestion-more"
                />
            </LemonMenu>
        </div>
    )
}
