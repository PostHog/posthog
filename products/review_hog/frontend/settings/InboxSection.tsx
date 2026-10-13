import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

export function InboxSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <SceneSection
            title="Inbox"
            description="Pull requests the PostHog agent opens for Inbox reports assigned to you."
        >
            <SettingsTable>
                <SettingRow
                    title="Review PRs the agent opens for Inbox reports assigned to me"
                    description="Runs a Deep review."
                    project={<span className="text-xs text-secondary">Personal only</span>}
                    mine={
                        <LemonSwitch
                            aria-label="Review PRs the agent opens for Inbox reports assigned to me"
                            checked={settings?.review_inbox_prs ?? false}
                            onChange={(checked) => updateSettings({ review_inbox_prs: checked })}
                            disabledReason={disabledReason}
                            data-attr="review-hog-review-inbox-prs"
                        />
                    }
                />
                <SettingRow
                    title="Let Stamphog review my Inbox PRs"
                    description="Stamphog approves them when they pass."
                    project={<span className="text-xs text-secondary">Personal only</span>}
                    mine={
                        <LemonSwitch
                            aria-label="Let Stamphog review my Inbox PRs"
                            checked={settings?.stamphog_review_inbox_prs ?? false}
                            onChange={(checked) => updateSettings({ stamphog_review_inbox_prs: checked })}
                            disabledReason={
                                // A switch that is already on stays usable while disconnected, so
                                // turning it off never requires connecting Stamphog first.
                                settings && !settings.stamphog_connected && !settings.stamphog_review_inbox_prs
                                    ? 'Connect a repository to Stamphog first.'
                                    : disabledReason
                            }
                            data-attr="review-hog-stamphog-review-inbox-prs"
                        />
                    }
                />
            </SettingsTable>
        </SceneSection>
    )
}
