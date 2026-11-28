import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import {
    featureFlagLogic,
    getFeatureFlagPayload,
    peekFeatureFlag,
    reportFeatureFlagExposure,
} from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'

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

// posthog-js reports the page bootstrap's flags before /flags answers, and the bootstrap can hold an arm
// the server no longer assigns. A page reports only its first exposure of a flag, so showing that arm
// would count the viewer in it for the whole page. With flags disabled, the app's own flags are final.
function hasThisPageLoadsValue(flag: FeatureFlagKey): boolean {
    return (
        !!posthog.config?.advanced_disable_flags ||
        posthog.getFeatureFlagResult(flag, { fresh: true, send_event: false }) !== undefined
    )
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
    // An answer equal to the bootstrap leaves featureFlagLogic's values unchanged, so it renders nothing new.
    const [flagAnswered, setFlagAnswered] = useState(() => hasThisPageLoadsValue(flag))
    useEffect(() => posthog.onFeatureFlags(() => setFlagAnswered(hasThisPageLoadsValue(flag))), [flag])
    const flagValue = peekFeatureFlag(featureFlags, flag)
    const destinationFlag = DESTINATION_FLAGS[placement.destination]
    const destinationAvailable = !destinationFlag || !!peekFeatureFlag(featureFlags, destinationFlag)
    const eligible =
        receivedFeatureFlags &&
        flagAnswered &&
        destinationAvailable &&
        !isDismissed &&
        !messageAudienceAccessDisabledReason()
    const state = placementState(key, { value: () => flagValue, payload: () => getFeatureFlagPayload(flag) })
    const showingTo = eligible && state.active ? viewerId : null
    const attemptId = useMemo(() => (showingTo === null ? undefined : uuid()), [showingTo])

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
            captureMessageAudienceClicked(key, state.placement.destination, attemptId)
        },
        onDismiss: dismiss,
    }
}
