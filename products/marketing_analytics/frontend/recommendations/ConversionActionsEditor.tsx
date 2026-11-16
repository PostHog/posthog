import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCheckbox, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { MarketingAnalyticsConversionAction } from '~/queries/schema/schema-general'

import { isPrimaryConversionAction, withConversionAction } from './conversionActions'
import { conversionActionsLogic } from './conversionActionsLogic'

function conversionCount(action: MarketingAnalyticsConversionAction): string {
    if (!action.recent) {
        return 'No conversions in the last 90 days'
    }
    const count = action.allConversions
    return `${humanFriendlyNumber(count)} ${count === 1 ? 'conversion' : 'conversions'} in the last 90 days`
}

export function ConversionActionsEditor(): JSX.Element {
    const {
        response,
        responseLoading,
        loadFailed,
        accounts,
        unmatchedActions,
        selection,
        changed,
        currentTeamLoading,
    } = useValues(conversionActionsLogic)
    const { loadOptions, setSelection, save } = useActions(conversionActionsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (loadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadOptions, loading: responseLoading }}
            >
                Could not load the Google Ads conversion actions.
            </LemonBanner>
        )
    }
    if (!response) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-5 w-80" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }
    if (accounts.length === 0 && unmatchedActions.length === 0 && !changed) {
        return (
            <p className="mb-0 text-secondary">
                No Google Ads conversion actions yet. They show up here once a Google Ads source syncs its campaign
                conversion action table. Until then, recommendations count each account's primary conversion actions.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <p className="mb-0 text-secondary">
                Choose the conversion actions that count as conversions in recommendations. An account with no action
                checked counts its primary actions, the ones Google Ads optimizes for. This applies to everyone in the
                project.
            </p>
            {accounts.map((account) => (
                <div key={account.campaignTable} className="flex flex-col gap-1 rounded border px-3 py-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-semibold">{account.account}</span>
                        {account.countsPrimary && (
                            <LemonTag type="muted" size="small">
                                Counting primary actions
                            </LemonTag>
                        )}
                    </div>
                    {account.actions.map((action) => (
                        <LemonCheckbox
                            key={action.action}
                            checked={selection.includes(action.action)}
                            onChange={(checked) =>
                                setSelection(withConversionAction(selection, action.action, checked))
                            }
                            disabledReason={restrictedReason}
                            label={
                                <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                                    <span translate="no">{action.name}</span>
                                    {isPrimaryConversionAction(action) && (
                                        <LemonTag type="muted" size="small">
                                            Primary
                                        </LemonTag>
                                    )}
                                    <span className="text-xs text-secondary">{conversionCount(action)}</span>
                                </span>
                            }
                            data-attr="marketing-recommendations-conversion-action"
                        />
                    ))}
                </div>
            ))}
            {unmatchedActions.length > 0 && (
                <div className="flex flex-col gap-1 rounded border px-3 py-2">
                    <span className="font-semibold">Not reported by any synced account</span>
                    <span className="text-xs text-secondary">
                        These saved actions still count for the account they belong to. Remove them if that account is
                        gone.
                    </span>
                    {unmatchedActions.map((action) => (
                        <div key={action} className="flex items-center justify-between gap-2">
                            <span className="truncate" translate="no">
                                {action}
                            </span>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setSelection(withConversionAction(selection, action, false))}
                                disabledReason={restrictedReason}
                                data-attr="marketing-recommendations-conversion-action-remove"
                            >
                                Remove
                            </LemonButton>
                        </div>
                    ))}
                </div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setSelection([])}
                    disabledReason={
                        restrictedReason ?? (selection.length === 0 ? 'Primary actions already count' : undefined)
                    }
                    data-attr="marketing-recommendations-conversion-actions-primary"
                >
                    Count primary actions
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={save}
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason ?? (changed ? undefined : 'No changes to save')}
                    data-attr="marketing-recommendations-conversion-actions-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
