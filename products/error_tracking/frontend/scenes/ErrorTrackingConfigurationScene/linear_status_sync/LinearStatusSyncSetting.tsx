import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { linearStatusSyncLogic } from './linearStatusSyncLogic'

export function LinearStatusSyncSetting(): JSX.Element {
    const { linearStatusSyncEnabled, settingsLoading, settingsLoadFailed, integrations, linearIntegrations } =
        useValues(linearStatusSyncLogic)
    const { setLinearStatusSyncEnabled } = useActions(linearStatusSyncLogic)

    if (linearStatusSyncEnabled === null) {
        return settingsLoadFailed ? (
            <LemonBanner type="error">Couldn't load this setting. Refresh the page to try again.</LemonBanner>
        ) : (
            <LemonSkeleton className="w-60 h-10" />
        )
    }

    // Turning the sync off stays possible after the workspace is disconnected.
    const noWorkspaceReason =
        integrations !== null && linearIntegrations.length === 0 && !linearStatusSyncEnabled
            ? 'Connect a Linear workspace first'
            : null

    return (
        <div className="flex flex-col gap-y-2">
            <LemonSwitch
                id="error-tracking-linear-status-sync-switch"
                data-attr="error-tracking-linear-status-sync-switch"
                label="Sync error tracking issue status from Linear"
                checked={linearStatusSyncEnabled}
                onChange={setLinearStatusSyncEnabled}
                loading={settingsLoading || integrations === null}
                disabledReason={errorTrackingEditAccessDisabledReason() ?? noWorkspaceReason}
                bordered
            />
            <p className="m-0 text-xs text-secondary">
                Resolves an error tracking issue when all of its linked Linear tickets are closed and at least one of
                them is done. Reopens the issue when a linked ticket is reopened.
            </p>
        </div>
    )
}
