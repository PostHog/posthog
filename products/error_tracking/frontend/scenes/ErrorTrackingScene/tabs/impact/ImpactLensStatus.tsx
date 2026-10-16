import { useActions } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { ErrorTrackingRecommendation } from '../recommendations/types'
import { type ImpactLensState, impactTabLogic } from './impactTabLogic'

export function ImpactLensStatus({
    lens,
    state,
}: {
    lens: ErrorTrackingRecommendation
    state: ImpactLensState
}): JSX.Element {
    const { refreshLens } = useActions(impactTabLogic)
    const status =
        state === 'computing'
            ? 'Calculating'
            : lens.computed_at === null
              ? 'Not calculated yet'
              : `Updated ${dayjs(lens.computed_at).fromNow()}`

    return (
        <div className="flex items-center gap-1">
            <Text render={<span />} size="xs" variant="muted">
                {status}
            </Text>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon-xs"
                            aria-label="Refresh this lens"
                            loading={state === 'computing'}
                            onClick={() => refreshLens(lens.id)}
                            data-attr="error-tracking-impact-lens-refresh"
                        />
                    }
                >
                    <IconRefresh />
                </TooltipTrigger>
                <TooltipContent>Refresh this lens</TooltipContent>
            </Tooltip>
        </div>
    )
}
