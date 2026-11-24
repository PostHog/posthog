import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HOST_LIST_FIELD, IP_LIST_FIELD } from './featureFlagRequestListField'
import { FeatureFlagRequestLists } from './FeatureFlagRequestLists'
import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'
import { FirstAllowedIpsModal } from './FirstAllowedIpsModal'
import { QuillFirstAllowedIpsDialog } from './QuillFirstAllowedIpsDialog'

export function FeatureFlagRequestAllowlist(): JSX.Element {
    const { allowedHosts, allowedIps } = useValues(featureFlagRequestListsLogic)
    const { setAllowedHosts, setAllowedIps } = useActions(featureFlagRequestListsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <>
            <FeatureFlagRequestLists
                lists={[
                    {
                        ...HOST_LIST_FIELD,
                        id: 'feature-flag-allowed-hosts',
                        dataAttr: 'feature-flag-allowed-hosts-select',
                        label: 'Allowed domains',
                        help: "Only pages on these domains get flags. Server-side and mobile SDKs aren't checked. Pages that hide their domain, such as local files and sandboxed frames, get no flags. A domain also allows its subdomains. Add up to 100 domains.",
                        value: allowedHosts,
                        onChange: setAllowedHosts,
                    },
                    {
                        ...IP_LIST_FIELD,
                        id: 'feature-flag-allowed-ips',
                        dataAttr: 'feature-flag-allowed-ips-select',
                        label: 'Allowed IP addresses',
                        help: "Only requests from these addresses get flags. This includes your servers and your users' browsers, even on allowed domains, so leave it empty unless every caller has a fixed address. Behind a reverse proxy, the proxy's address is checked, so allowed IP addresses don't work with the managed reverse proxy. Enter up to 100 single addresses or CIDR ranges.",
                        value: allowedIps,
                        onChange: setAllowedIps,
                    },
                ]}
            />
            {todayRailNav ? <QuillFirstAllowedIpsDialog /> : <FirstAllowedIpsModal />}
        </>
    )
}
