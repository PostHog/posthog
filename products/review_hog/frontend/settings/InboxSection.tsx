import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { YouMark } from 'products/review_hog/frontend/repositories/YouMark'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

/**
 * Inbox reviews are internal for now. A switch that is on stays visible anywhere, so the user can
 * still turn it off.
 */
export function InboxSection(): JSX.Element | null {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const internal = !!featureFlags[FEATURE_FLAGS.REVIEW_HOG_INTERNAL]
    const showInbox = internal || (settings?.review_inbox_prs ?? false)
    const showStamphog = internal || (settings?.stamphog_review_inbox_prs ?? false)
    if (!showInbox && !showStamphog) {
        return null
    }
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <SettingsTable
            title="Inbox"
            description="Pull requests the PostHog agent opens for Inbox reports. The PostHog app authors them, so the report's assigned reviewer counts as their owner."
        >
            {showInbox && (
                <SettingRow
                    title="Review PRs the agent opens for Inbox reports assigned to me"
                    description="Full review today. Moves to Flash once Flash is stable."
                    project={<span className="text-xs text-secondary">Default: off</span>}
                    mine={
                        <>
                            <YouMark shown={settings?.review_inbox_prs ?? false} />
                            <LemonSwitch
                                aria-label="Review PRs the agent opens for Inbox reports assigned to me"
                                checked={settings?.review_inbox_prs ?? false}
                                onChange={(checked) => updateSettings({ review_inbox_prs: checked })}
                                disabledReason={disabledReason}
                                data-attr="review-hog-review-inbox-prs"
                            />
                        </>
                    }
                />
            )}
            {showStamphog && (
                <SettingRow
                    title="Let Stamphog review my Inbox PRs"
                    description="Stamphog reviews the same pull requests and approves them when they pass."
                    project={<span className="text-xs text-secondary">Default: off</span>}
                    mine={
                        <>
                            <YouMark shown={settings?.stamphog_review_inbox_prs ?? false} />
                            <LemonSwitch
                                aria-label="Let Stamphog review my Inbox PRs"
                                checked={settings?.stamphog_review_inbox_prs ?? false}
                                onChange={(checked) => updateSettings({ stamphog_review_inbox_prs: checked })}
                                disabledReason={
                                    // A switch that is already on stays usable while disconnected, so
                                    // turning it off never requires connecting Stamphog first.
                                    settings && !settings.stamphog_connected && !settings.stamphog_review_inbox_prs
                                        ? 'Connect a repository to Stamphog first. Stamphog is not set up for this project yet.'
                                        : disabledReason
                                }
                                data-attr="review-hog-stamphog-review-inbox-prs"
                            />
                        </>
                    }
                />
            )}
        </SettingsTable>
    )
}
