import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { YouMark } from 'products/review_hog/frontend/repositories/YouMark'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

export function InboxSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined

    return (
        <SettingsTable title="Inbox" description="Pull requests the PostHog agent opens for your Inbox reports.">
            <SettingRow
                title="Review my Inbox PRs"
                description="PostHog Review runs a Deep review on them."
                project={<span className="text-xs text-secondary">Default: off</span>}
                mine={
                    <>
                        <LemonSwitch
                            aria-label="Review my Inbox PRs"
                            checked={settings?.review_inbox_prs ?? false}
                            onChange={(checked) => updateSettings({ review_inbox_prs: checked })}
                            disabledReason={disabledReason}
                            data-attr="review-hog-review-inbox-prs"
                        />
                        <YouMark shown={settings?.review_inbox_prs ?? false} />
                    </>
                }
            />
            <SettingRow
                title="Let Stamphog review my Inbox PRs"
                description="Stamphog approves them when they pass."
                project={<span className="text-xs text-secondary">Default: off</span>}
                mine={
                    <>
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
                        <YouMark shown={settings?.stamphog_review_inbox_prs ?? false} />
                    </>
                }
            />
        </SettingsTable>
    )
}
