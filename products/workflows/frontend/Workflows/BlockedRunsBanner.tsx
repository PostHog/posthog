import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { blockedRunsLogic } from './blockedRunsLogic'

// Status page entry where the public postmortem will live.
const INCIDENT_2026_04_22_URL = 'https://www.posthogstatus.com/eu?incident=01KPSY5YTTB1MEZ5KZVQ0W8NDZ'

function BlockedRunsBannerInner({ id }: { id: string }): JSX.Element | null {
    const { allBlockedRuns, blockedRunsLoading, hasMoreRuns } = useValues(blockedRunsLogic({ id }))

    if (blockedRunsLoading || allBlockedRuns.length === 0) {
        return null
    }

    const isPlural = hasMoreRuns || allBlockedRuns.length !== 1
    const runsLabel = hasMoreRuns
        ? `${allBlockedRuns.length}+ ${pluralize(2, 'run', undefined, false)}`
        : pluralize(allBlockedRuns.length, 'run')
    const verbWord = isPlural ? 'were' : 'was'

    return (
        <div className="py-2">
            <LemonBanner
                type="warning"
                action={{
                    children: 'View blocked runs',
                    onClick: () => router.actions.push(urls.workflow(id, 'blocked_runs')),
                }}
            >
                {runsLabel} on this workflow {verbWord} silently blocked at a <strong>Wait until condition</strong> step
                between March 30 and April 22, 2026, due to a bug that has since been fixed. You can review and replay
                them.{' '}
                <Link to={INCIDENT_2026_04_22_URL} target="_blank">
                    Read more
                </Link>
                .
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
