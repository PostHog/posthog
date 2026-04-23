import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { urls } from 'scenes/urls'

import { blockedRunsLogic } from './blockedRunsLogic'

function BlockedRunsBannerInner({ id }: { id: string }): JSX.Element | null {
    const { allBlockedRuns, blockedRunsLoading, hasMoreRuns } = useValues(blockedRunsLogic({ id }))

    if (blockedRunsLoading || allBlockedRuns.length === 0) {
        return null
    }

    const countLabel = hasMoreRuns ? `${allBlockedRuns.length}+` : `${allBlockedRuns.length}`

    return (
        <div className="px-4 pt-2">
            <LemonBanner
                type="warning"
                action={{
                    children: 'View blocked runs',
                    onClick: () => router.actions.push(urls.workflow(id, 'blocked_runs')),
                }}
            >
                {countLabel} workflow run{allBlockedRuns.length !== 1 ? 's were' : ' was'} blocked by a bug and did not
                complete. You can review and replay them.
            </LemonBanner>
        </div>
    )
}

export function BlockedRunsBanner({ id }: { id?: string }): JSX.Element | null {
    const safeId = id && id !== 'new' ? id : undefined
    if (!safeId) {
        return null
    }
    return <BlockedRunsBannerInner id={safeId} />
}
