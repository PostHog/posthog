import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsList } from './SettingsList'

export function InboxSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <SceneSection
            title="Inbox"
            description="These cover pull requests the PostHog agent opens for your Inbox reports."
        >
            <SettingsList>
                <SettingRow title="Review my Inbox PRs" description="PostHog Review runs a Deep review on them.">
                    <LemonSwitch
                        aria-label="Review my Inbox PRs"
                        checked={settings?.review_inbox_prs ?? false}
                        onChange={(checked) => updateSettings({ review_inbox_prs: checked })}
                        disabledReason={disabledReason}
                        data-attr="review-hog-review-inbox-prs"
                    />
                </SettingRow>
                <SettingRow
                    title="Let Stamphog review my Inbox PRs"
                    description="Stamphog approves them when they pass."
                >
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
                </SettingRow>
            </SettingsList>
        </SceneSection>
    )
}
