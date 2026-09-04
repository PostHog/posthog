import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ScoutChatType } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutSuggestButton } from './ScoutSuggestButton'

/** Actions for the roster, lifted into the scene header so they sit in one predictable place. */
export function ScoutsRosterActions(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const suggestionsEnabled = !!featureFlags[FEATURE_FLAGS.SCOUTS_SUGGESTED_SCOUTS]
    return (
        <>
            <AskAboutScoutsMenu />
            {/* Without the suggestions strip this button is the only way to ask for a pick, so it
                keeps its place in the header until the strip reaches everyone. */}
            {!suggestionsEnabled && <ScoutSuggestButton type="secondary" size="small" />}
            <ScoutCreateButton size="small" onCreated={() => loadScoutConfigs()} />
        </>
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
    const prompts: { label: string; chatType: ScoutChatType }[] = [
        ...(featureFlags[FEATURE_FLAGS.SCOUTS_SUGGESTED_SCOUTS]
            ? [{ label: 'Suggest a scout', chatType: 'author_scout' as ScoutChatType }]
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
