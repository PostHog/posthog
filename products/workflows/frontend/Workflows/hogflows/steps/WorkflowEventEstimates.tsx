import { useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { humanFriendlyNumber } from 'lib/utils'

import { workflowLogic } from '../../workflowLogic'

export function WorkflowEventEstimates(): JSX.Element | null {
    const { sparkline, sparklineLoading, triggerAction } = useValues(workflowLogic)

    if (!triggerAction || triggerAction.config.type !== 'event') {
        return null
    }

    return (
        <div className="relative p-3 rounded border bg-surface-primary">
            <div className="font-medium text-xs mb-1">Estimated volume</div>
            {sparkline && !sparklineLoading ? (
                <>
                    <p className="text-xs text-muted mb-1">
                        Based on the last 7 days, this trigger would have fired approximately{' '}
                        <strong>
                            {humanFriendlyNumber(sparkline.count)} time{sparkline.count !== 1 ? 's' : ''}
                        </strong>
                        .
                    </p>
                    <Sparkline type="bar" className="w-full h-14" data={sparkline.data} labels={sparkline.labels} />
                </>
            ) : sparklineLoading ? (
                <div className="min-h-14">
                    <SpinnerOverlay />
                </div>
            ) : (
                <p className="text-xs text-muted mb-0">Add a trigger event to see estimated volume.</p>
            )}
        </div>
    )
}
