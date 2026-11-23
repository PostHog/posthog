import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'
import { QuillFeatureFlagRequestAllowlist } from './QuillFeatureFlagRequestAllowlist'

export function FeatureFlagRequestAllowlist(): JSX.Element {
    const { currentTeam, currentTeamLoading, allowedHosts, allowedIps } = useValues(featureFlagRequestListsLogic)
    const { setAllowedHosts, setAllowedIps } = useActions(featureFlagRequestListsLogic)
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
            <QuillFeatureFlagRequestAllowlist
                allowedHosts={allowedHosts}
                allowedIps={allowedIps}
                onAllowedHostsChange={setAllowedHosts}
                onAllowedIpsChange={setAllowedIps}
                disabled={currentTeamLoading}
                // Chip removal only honors the disabled reason, and a removal during a save would send the old list.
                disabledReason={restrictedReason ?? (currentTeamLoading ? 'Loading…' : null)}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonField.Pure
                label="Allowed domains"
                htmlFor="feature-flag-allowed-hosts"
                help="Only pages on these domains get flags. This list doesn't check server-side SDKs, mobile SDKs, or scripts that send no domain. A domain also allows its subdomains. Add up to 100 domains."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={allowedHosts}
                    onChange={setAllowedHosts}
                    placeholder="example.com"
                    id="feature-flag-allowed-hosts"
                    data-attr="feature-flag-allowed-hosts-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Allowed IP addresses"
                htmlFor="feature-flag-allowed-ips"
                help="Only requests from these addresses get flags. This includes your servers and your users' browsers, so leave it empty unless every caller has a fixed address. Enter up to 100 single addresses or CIDR ranges."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={allowedIps}
                    onChange={setAllowedIps}
                    placeholder="203.0.113.7 or 198.51.100.0/24"
                    id="feature-flag-allowed-ips"
                    data-attr="feature-flag-allowed-ips-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
            </LemonField.Pure>
        </div>
    )
}
