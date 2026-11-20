import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { featureFlagRequestBlocklistLogic } from './featureFlagRequestBlocklistLogic'
import { QuillFeatureFlagRequestBlocklist } from './QuillFeatureFlagRequestBlocklist'

export function FeatureFlagRequestBlocklist(): JSX.Element {
    const { currentTeam, currentTeamLoading, blockedHosts, blockedIps } = useValues(featureFlagRequestBlocklistLogic)
    const { setBlockedHosts, setBlockedIps } = useActions(featureFlagRequestBlocklistLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 max-w-160" /> : <LemonSkeleton />
    }

    if (todayRailNav) {
        return (
            <QuillFeatureFlagRequestBlocklist
                blockedHosts={blockedHosts}
                blockedIps={blockedIps}
                onBlockedHostsChange={setBlockedHosts}
                onBlockedIpsChange={setBlockedIps}
                disabled={currentTeamLoading}
                // Chip removal only honors the disabled reason, and a removal during a save would send the old list.
                disabledReason={restrictedReason ?? (currentTeamLoading ? 'Loading...' : null)}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonField.Pure
                label="Blocked domains"
                htmlFor="feature-flag-blocked-hosts"
                help="Stops other websites that embed your project token from requesting flags. A domain also blocks its subdomains. Add up to 100 domains."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={blockedHosts}
                    onChange={setBlockedHosts}
                    placeholder="example.com"
                    id="feature-flag-blocked-hosts"
                    data-attr="feature-flag-blocked-hosts-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Blocked IP addresses"
                htmlFor="feature-flag-blocked-ips"
                help="Stops scripts that request flags from known addresses. Enter up to 100 single addresses or CIDR ranges."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={blockedIps}
                    onChange={setBlockedIps}
                    placeholder="203.0.113.7 or 198.51.100.0/24"
                    id="feature-flag-blocked-ips"
                    data-attr="feature-flag-blocked-ips-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </LemonField.Pure>
        </div>
    )
}
