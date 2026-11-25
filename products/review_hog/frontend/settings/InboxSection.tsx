import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { YouMark } from 'products/review_hog/frontend/repositories/YouMark'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

export function InboxSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined
    // A switch that is already on stays usable while disconnected, so turning it off never requires
    // connecting a repository first.
    const needsConnection = !!settings && !settings.approval_connected && !settings.approval_review_inbox_prs

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
                title="Auto-approve my Inbox PRs"
                description={
                    needsConnection ? (
                        <>
                            Auto-approval approves them when they pass.{' '}
                            <Link
                                to={urls.codeReview('approval_settings')}
                                data-attr="review-hog-inbox-auto-approval-link"
                            >
                                Add a repository to auto-approval first.
                            </Link>
                        </>
                    ) : (
                        'Auto-approval approves them when they pass.'
                    )
                }
                project={<span className="text-xs text-secondary">Default: off</span>}
                mine={
                    <>
                        <LemonSwitch
                            aria-label="Auto-approve my Inbox PRs"
                            checked={settings?.approval_review_inbox_prs ?? false}
                            onChange={(checked) => updateSettings({ approval_review_inbox_prs: checked })}
                            disabledReason={
                                needsConnection ? 'Add a repository to auto-approval first' : disabledReason
                            }
                            data-attr="review-hog-stamphog-review-inbox-prs"
                        />
                        <YouMark shown={settings?.approval_review_inbox_prs ?? false} />
                    </>
                }
            />
        </SettingsTable>
    )
}
