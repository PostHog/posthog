import { useAsyncActions, useValues } from 'kea'

import { LemonButton, LemonButtonPropsBase } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { canFreezeExposure, confirmFreezeExposure } from '../experimentActions'
import { getTotalExposures } from './exposureHealth'

export function HealthFreezeExposureButton({
    buttonProps,
    onClick,
}: {
    buttonProps: Pick<LemonButtonPropsBase, 'size' | 'type' | 'data-attr' | 'disabledReason'>
    onClick: () => void
}): JSX.Element | null {
    const { experiment, exposures, freezeExposureLoading } = useValues(experimentLogic)
    const { freezeExposure } = useAsyncActions(experimentLogic)

    // The health answer can predate a freeze or pause made on this page, so the button checks again.
    if (!canFreezeExposure(experiment)) {
        return null
    }
    return (
        <LemonButton
            {...buttonProps}
            disabledReason={buttonProps.disabledReason || (freezeExposureLoading ? 'Freezing exposure...' : null)}
            onClick={() => {
                onClick()
                confirmFreezeExposure(() => freezeExposure(), getTotalExposures(exposures))
            }}
        >
            Freeze exposure
        </LemonButton>
    )
}
