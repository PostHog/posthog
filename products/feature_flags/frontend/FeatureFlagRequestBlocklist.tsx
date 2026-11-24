import { useActions, useValues } from 'kea'

import { HOST_LIST_FIELD, IP_LIST_FIELD } from './featureFlagRequestListField'
import { FeatureFlagRequestLists } from './FeatureFlagRequestLists'
import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'

export function FeatureFlagRequestBlocklist(): JSX.Element {
    const { blockedHosts, blockedIps } = useValues(featureFlagRequestListsLogic)
    const { setBlockedHosts, setBlockedIps } = useActions(featureFlagRequestListsLogic)

    return (
        <FeatureFlagRequestLists
            lists={[
                {
                    ...HOST_LIST_FIELD,
                    id: 'feature-flag-blocked-hosts',
                    dataAttr: 'feature-flag-blocked-hosts-select',
                    label: 'Blocked domains',
                    help: 'Stops other websites that embed your project token from requesting flags. A domain also blocks its subdomains. Add up to 100 domains.',
                    value: blockedHosts,
                    onChange: setBlockedHosts,
                },
                {
                    ...IP_LIST_FIELD,
                    id: 'feature-flag-blocked-ips',
                    dataAttr: 'feature-flag-blocked-ips-select',
                    label: 'Blocked IP addresses',
                    help: 'Stops scripts that request flags from known addresses. Enter up to 100 single addresses or CIDR ranges.',
                    value: blockedIps,
                    onChange: setBlockedIps,
                },
            ]}
        />
    )
}
