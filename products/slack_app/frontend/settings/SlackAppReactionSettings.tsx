import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type {
    SlackAppReactionChoiceApi,
    SlackAppReactionChoicesApi,
    SlackAppResolvedReactionsApi,
} from '../generated/api.schemas'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import { SlackEmojiSelect } from './SlackEmojiSelect'
import { slackReactionEmojiLogic } from './slackReactionEmojiLogic'

type ReactionKind = keyof SlackAppResolvedReactionsApi

const REACTION_KINDS: { kind: ReactionKind; label: string; description: string }[] = [
    { kind: 'working', label: 'Working', description: 'Added when PostHog starts on a message.' },
    { kind: 'done', label: 'Done', description: 'Added when PostHog replies. The working reaction is removed.' },
    { kind: 'error', label: 'Error', description: 'Added when PostHog could not finish the request.' },
    { kind: 'polite', label: 'Thank you', description: 'Added to a message that says please or thanks.' },
]

function choiceOf(choices: SlackAppReactionChoicesApi, kind: ReactionKind): SlackAppReactionChoiceApi {
    return choices[kind] ?? {}
}

function CustomEmojiNotice({ integrationId }: { integrationId: number }): JSX.Element | null {
    const { catalog, catalogLoadFailed } = useValues(slackReactionEmojiLogic({ integrationId }))
    if (catalogLoadFailed || catalog?.custom_emoji_status === 'unavailable') {
        return (
            <p className="text-secondary text-xs m-0">
                Couldn't load this workspace's custom emoji. Standard emoji are listed. Refresh the page to try again.
            </p>
        )
    }
    if (catalog?.custom_emoji_status === 'missing_scope') {
        return (
            <p className="text-secondary text-xs m-0">
                Only standard emoji are listed, because this Slack connection can't read the workspace's custom emoji.
            </p>
        )
    }
    return null
}

/** The emoji PostHog reacts with in Slack, for the whole workspace or for this person's own messages. */
export function SlackAppReactionSettings({ level }: { level: 'workspace' | 'personal' }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { settings, selectedIntegrationId, workspaceSettingsDisabledReason, personalSettingsDisabledReason } =
        useValues(slackAppSettingsLogic)
    const { updateWorkspaceSettings, updatePersonalSettings } = useActions(slackAppSettingsLogic)

    if (!featureFlags[FEATURE_FLAGS.SLACK_APP_EMOJIS_SETTINGS] || !settings || selectedIntegrationId === null) {
        return null
    }

    const isWorkspace = level === 'workspace'
    const choices = isWorkspace ? settings.workspace.reactions : settings.personal.reactions
    const effective = isWorkspace ? settings.workspace.effective_reactions : settings.personal.effective_reactions
    const disabledReason = isWorkspace ? workspaceSettingsDisabledReason : personalSettingsDisabledReason

    // The API replaces every choice of the level at once, so a change sends the other kinds unchanged.
    const save = (kind: ReactionKind, choice: SlackAppReactionChoiceApi): void => {
        const reactions: SlackAppReactionChoicesApi = { ...choices, [kind]: choice }
        if (isWorkspace) {
            updateWorkspaceSettings({ reactions })
        } else {
            updatePersonalSettings({ reactions })
        }
    }

    return (
        // The workspace tab stacks its settings tightly, so the section keeps its distance itself.
        <section className={isWorkspace ? 'flex flex-col gap-2 mt-4' : 'flex flex-col gap-2'}>
            <div>
                <h3 className="text-sm font-semibold m-0">Reactions</h3>
                <p className="text-secondary text-xs m-0">
                    {isWorkspace
                        ? 'The emoji PostHog adds to messages in this workspace. People can pick their own in their personal settings.'
                        : 'The emoji PostHog adds to your messages. A reaction you have not changed follows the workspace choice.'}
                </p>
            </div>
            <div className="rounded border bg-surface-primary divide-y">
                {REACTION_KINDS.map(({ kind, label, description }) => {
                    const choice = choiceOf(choices, kind)
                    const ownChoice = choice.emoji != null || choice.enabled != null
                    return (
                        <div
                            key={kind}
                            className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3"
                        >
                            <div className="flex-1 min-w-60">
                                <div className="font-semibold">{label}</div>
                                <div className="text-secondary text-sm">{description}</div>
                            </div>
                            <div className="flex flex-wrap items-center justify-end gap-2">
                                {!isWorkspace && ownChoice ? (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        onClick={() => save(kind, {})}
                                        disabledReason={disabledReason}
                                        tooltip="Use the workspace choice again"
                                        data-attr={`slack-app-settings-reaction-${kind}-reset`}
                                    >
                                        Reset
                                    </LemonButton>
                                ) : null}
                                <SlackEmojiSelect
                                    integrationId={selectedIntegrationId}
                                    value={effective[kind].emoji}
                                    onChange={(emoji) => save(kind, { ...choice, emoji })}
                                    disabledReason={disabledReason}
                                    dataAttr={`slack-app-settings-${level}-reaction-${kind}`}
                                />
                                <LemonSwitch
                                    checked={effective[kind].enabled}
                                    onChange={(enabled) => save(kind, { ...choice, enabled })}
                                    disabledReason={disabledReason}
                                    aria-label={`${label} reaction`}
                                    data-attr={`slack-app-settings-${level}-reaction-${kind}-enabled`}
                                />
                            </div>
                        </div>
                    )
                })}
            </div>
            <CustomEmojiNotice integrationId={selectedIntegrationId} />
        </section>
    )
}
