import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { featureFlagRequestListsLogic } from './featureFlagRequestListsLogic'
import { FIRST_ALLOWED_IPS_COPY } from './firstAllowedIpsCopy'

export function FirstAllowedIpsModal(): JSX.Element {
    const { firstAllowedIps } = useValues(featureFlagRequestListsLogic)
    const { cancelFirstAllowedIps, confirmFirstAllowedIps } = useActions(featureFlagRequestListsLogic)

    return (
        <LemonModal
            isOpen={!!firstAllowedIps}
            onClose={cancelFirstAllowedIps}
            title={FIRST_ALLOWED_IPS_COPY.title}
            width="30rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={cancelFirstAllowedIps}>
                        {FIRST_ALLOWED_IPS_COPY.cancel}
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={() => firstAllowedIps && confirmFirstAllowedIps(firstAllowedIps)}
                        data-attr="feature-flag-allowed-ips-confirm"
                    >
                        {FIRST_ALLOWED_IPS_COPY.confirm}
                    </LemonButton>
                </>
            }
        >
            <p className="m-0">{FIRST_ALLOWED_IPS_COPY.description}</p>
        </LemonModal>
    )
}
