import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { ScoutChatType } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { ScoutCreateButton } from './ScoutCreateButton'
import { ScoutSuggestButton } from './ScoutSuggestButton'

/** Actions for the roster, lifted into the scene header so they sit in one predictable place. */
export function ScoutsRosterActions(): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)
    return (
        <>
            <AskAboutScoutsMenu />
            <ScoutSuggestButton type="secondary" size="small" />
            <ScoutCreateButton size="small" onCreated={() => loadScoutConfigs()} />
        </>
    )
}

/**
 * The templated chat kickoffs, behind one button. As peers of "Create scout" they read as primary
 * actions, which they aren't — each one navigates away to a task rather than changing anything here.
 */
function AskAboutScoutsMenu(): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const prompts: { label: string; chatType: ScoutChatType }[] = [
        { label: 'How is my scout troop performing?', chatType: 'fleet_overview' },
        { label: 'What signals were emitted recently?', chatType: 'recent_signals' },
    ]

    return (
        <LemonMenu
            items={prompts.map(({ label, chatType }) => ({
                label,
                onClick: () => startScoutChatTask(chatType, label),
                disabledReason: runningChatType !== null ? 'Starting a task…' : (aiConsentDisabledReason ?? undefined),
            }))}
        >
            <LemonButton type="secondary" size="small" icon={<IconSparkles />} loading={runningChatType !== null}>
                Ask
            </LemonButton>
        </LemonMenu>
    )
}
