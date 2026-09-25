import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ScoutChatType } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'
import { ScoutNewButton } from './ScoutNewButton'

/** Actions for the roster, lifted into the scene header so they sit in one predictable place. */
export function ScoutsRosterActions(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const suggestionsEnabled = !!featureFlags[FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]
    return (
        <>
            <AskAboutScoutsMenu />
            {suggestionsEnabled ? <ShowSuggestionsButton /> : null}
            <ScoutNewButton surface="fleet_list" size="small" onCreated={() => loadScoutConfigs()} />
        </>
    )
}

/**
 * Takes the "Suggest a scout" spot whenever the strip has no picks to show. With picks waiting it
 * reopens the closed strip; with none it opens the authoring chat.
 */
function ShowSuggestionsButton(): JSX.Element | null {
    const { suggestButtonVisible, hasPicks, isRefreshing, suggestionSetLoading, aiConsentDisabledReason } =
        useValues(scoutSuggestionsLogic)
    const { runningChatType } = useValues(scoutFleetLogic)
    const { askForSuggestions } = useActions(scoutSuggestionsLogic)
    // Opening the chat ends in a skill write, so it carries the editor gate. Reopening needs neither.
    const creationDisabledReason = useScoutCreateDisabledReason()
    if (!suggestButtonVisible) {
        return null
    }
    const busyReason = showSuggestionsBusyReason({ hasPicks, isRefreshing, suggestionSetLoading, runningChatType })
    const gateReason = hasPicks ? null : (creationDisabledReason ?? aiConsentDisabledReason)
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            loading={!!busyReason}
            disabledReason={busyReason ?? gateReason ?? undefined}
            onClick={() => askForSuggestions()}
            data-attr="scout-suggestions-show"
        >
            Suggest a scout
        </LemonButton>
    )
}

function showSuggestionsBusyReason({
    hasPicks,
    isRefreshing,
    suggestionSetLoading,
    runningChatType,
}: {
    hasPicks: boolean
    isRefreshing: boolean
    suggestionSetLoading: boolean
    runningChatType: ScoutChatType | null
}): string | null {
    // With picks waiting, the press only reopens the strip: no read, no task. Nothing else the
    // header is doing holds that up, and every reason below would name work it never starts.
    if (hasPicks) {
        return null
    }
    if (suggestionSetLoading) {
        return 'Reading the suggestions…'
    }
    // A scan already running is the answer to the press, so say so instead of opening a chat on top.
    if (isRefreshing) {
        return 'Scanning the project…'
    }
    if (runningChatType === 'author_scout') {
        return 'Starting a task…'
    }
    if (runningChatType !== null) {
        return 'Starting another task…'
    }
    return null
}

/**
 * The templated chat kickoffs, behind one button. As peers of "New scout" they read as primary
 * actions, which they aren't — each one navigates away to a task rather than changing anything here.
 * Creating a scout lives in "New scout", so this menu holds questions only.
 */
function AskAboutScoutsMenu(): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const prompts: { label: string; chatType: ScoutChatType }[] = [
        { label: 'How is my scout troop performing?', chatType: 'fleet_overview' },
        { label: 'What signals were emitted recently?', chatType: 'recent_signals' },
    ]
    // Only spin for this menu's own prompts, so kicking off a task from a sibling button
    // doesn't make every scout CTA in the header look like it's loading.
    const isStarting = prompts.some(({ chatType }) => chatType === runningChatType)
    const anotherTaskIsStarting = runningChatType !== null && !isStarting

    return (
        <LemonMenu
            items={prompts.map(({ label, chatType }) => ({
                label,
                onClick: () => startScoutChatTask(chatType, label),
                disabledReason: anotherTaskIsStarting
                    ? 'Starting another task…'
                    : isStarting
                      ? 'Starting a task…'
                      : (aiConsentDisabledReason ?? undefined),
            }))}
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSparkles />}
                loading={isStarting}
                disabledReason={anotherTaskIsStarting ? 'Starting another task…' : undefined}
            >
                Ask
            </LemonButton>
        </LemonMenu>
    )
}
