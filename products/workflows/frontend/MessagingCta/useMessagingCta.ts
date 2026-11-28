import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import {
    featureFlagLogic,
    getFeatureFlagPayload,
    peekFeatureFlag,
    reportFeatureFlagExposure,
} from 'lib/logic/featureFlagLogic'

import {
    MessagingCtaCopy,
    MessagingCtaDestination,
    MessagingPlacement,
    MessagingPlacementKey,
    areaFlag,
    placementFor,
    placementState,
} from '../../mcp/messagingPlacements'
import { captureMessageAudienceClicked, messageAudienceAccessDisabledReason } from '../MessageAudience/messageAudience'
import { messagingCtaDismissalLogic } from './messagingCtaDismissalLogic'

const DESTINATION_FLAGS: Partial<Record<MessagingCtaDestination, FeatureFlagKey>> = {
    send_from_code: FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API,
}

export interface MessagingCta {
    placement: MessagingPlacement
    copy: MessagingCtaCopy
    onClick: () => void
    onDismiss: () => void
}

export function useMessagingCta(key: MessagingPlacementKey, viewerId: string): MessagingCta | null {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { isDismissed } = useValues(messagingCtaDismissalLogic({ viewerId, placement: key }))
    const { dismiss } = useActions(messagingCtaDismissalLogic({ viewerId, placement: key }))

    const placement = placementFor(key)
    const flag = areaFlag(placement.area) as FeatureFlagKey
    const flagValue = peekFeatureFlag(featureFlags, flag)
    const destinationFlag = DESTINATION_FLAGS[placement.destination]
    const destinationAvailable = !destinationFlag || !!peekFeatureFlag(featureFlags, destinationFlag)
    const eligible =
        receivedFeatureFlags && destinationAvailable && !isDismissed && !messageAudienceAccessDisabledReason()
    const state = placementState(key, { value: () => flagValue, payload: () => getFeatureFlagPayload(flag) })

    useEffect(() => {
        if (eligible && typeof flagValue === 'string') {
            reportFeatureFlagExposure(featureFlags, flag)
        }
    }, [eligible, flagValue, featureFlags, flag])

    if (!eligible || !state.active) {
        return null
    }
    return {
        placement: state.placement,
        copy: state.copy,
        onClick: () => {
            captureMessageAudienceClicked(key, state.placement.destination)
        },
        onDismiss: dismiss,
    }
}
