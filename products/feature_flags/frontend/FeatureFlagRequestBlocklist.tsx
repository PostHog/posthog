import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { teamLogic } from 'scenes/teamLogic'

export function FeatureFlagRequestBlocklist(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [blockedHosts, setBlockedHosts] = useState<string[]>([])
    const [blockedIps, setBlockedIps] = useState<string[]>([])
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    useEffect(() => {
        setBlockedHosts(currentTeam?.feature_flag_policy_config?.blocked_hosts ?? [])
        setBlockedIps(currentTeam?.feature_flag_policy_config?.blocked_ips ?? [])
    }, [currentTeam])

    if (!currentTeam) {
        return <LemonSkeleton />
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonField.Pure
                label="Blocked domains"
                help="Stops other websites that embed your project token from requesting flags. A domain also blocks its subdomains."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={blockedHosts}
                    onChange={setBlockedHosts}
                    placeholder="example.com"
                    data-attr="feature-flag-blocked-hosts-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading || !!restrictedReason}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Blocked IP addresses"
                help="Stops scripts that request flags from known addresses. Enter single addresses or CIDR ranges."
            >
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={blockedIps}
                    onChange={setBlockedIps}
                    placeholder="203.0.113.7 or 198.51.100.0/24"
                    data-attr="feature-flag-blocked-ips-select"
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading || !!restrictedReason}
                />
            </LemonField.Pure>
            <div>
                <LemonButton
                    type="primary"
                    data-attr="feature-flag-request-blocklist-save"
                    onClick={() =>
                        updateCurrentTeam({
                            feature_flag_policy_config: { blocked_hosts: blockedHosts, blocked_ips: blockedIps },
                        })
                    }
                    loading={currentTeamLoading}
                    disabledReason={restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
