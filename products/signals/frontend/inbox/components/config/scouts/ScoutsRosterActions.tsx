import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ScoutChatType } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'
import { ScoutSuggestButton } from './ScoutSuggestButton'

/** Actions for the roster, lifted into the scene header so they sit in one predictable place. */
export function ScoutsRosterActions(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const suggestionsEnabled = !!featureFlags[FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]
    return (
        <>
            <AskAboutScoutsMenu />
            {/* Without the suggestions strip this button is the only way to ask for a pick, so it
                keeps its place in the header until the strip reaches everyone. */}
            {suggestionsEnabled ? <ShowSuggestionsButton /> : <ScoutSuggestButton type="secondary" size="small" />}
            <ScoutCreateButton size="small" onCreated={() => loadScoutConfigs()} />
        </>
    )
}

/** Takes the "Suggest a scout" spot while the strip is closed, and reopens it in place of a chat. */
function ShowSuggestionsButton(): JSX.Element | null {
    const { hasBatch, stripHidden } = useValues(scoutSuggestionsLogic)
    const { showStrip } = useActions(scoutSuggestionsLogic)
    if (!hasBatch || !stripHidden) {
        return null
    }
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            onClick={() => showStrip()}
            data-attr="scout-suggestions-show"
        >
            Suggest a scout
        </LemonButton>
    )
}

/**
 * The templated chat kickoffs, behind one button. As peers of "Create scout" they read as primary
 * actions, which they aren't — each one navigates away to a task rather than changing anything here.
 * "Suggest a scout" joins them once the suggestions strip offers picks with nothing to wait for.
 */
function AskAboutScoutsMenu(): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // Authoring a scout ends in a skill write, so it keeps the editor gate the standalone button had.
    const creationDisabledReason = useScoutCreateDisabledReason()
    const prompts: { label: string; chatType: ScoutChatType; disabledReason?: string }[] = [
        ...(featureFlags[FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]
            ? [
                  {
                      label: 'Suggest a scout',
                      chatType: 'author_scout' as ScoutChatType,
                      disabledReason: creationDisabledReason ?? undefined,
                  },
              ]
            : []),
        { label: 'How is my scout troop performing?', chatType: 'fleet_overview' },
        { label: 'What signals were emitted recently?', chatType: 'recent_signals' },
    ]
    // Only spin for this menu's own prompts, so kicking off a task from a sibling button
    // doesn't make every scout CTA in the header look like it's loading.
    const isStarting = prompts.some(({ chatType }) => chatType === runningChatType)
    const anotherTaskIsStarting = runningChatType !== null && !isStarting

    return (
        <LemonMenu
            items={prompts.map(({ label, chatType, disabledReason }) => ({
                label,
                onClick: () => startScoutChatTask(chatType, label),
                disabledReason: anotherTaskIsStarting
                    ? 'Starting another task…'
                    : isStarting
                      ? 'Starting a task…'
                      : (disabledReason ?? aiConsentDisabledReason ?? undefined),
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
