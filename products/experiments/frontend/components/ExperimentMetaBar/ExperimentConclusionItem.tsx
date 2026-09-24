import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'

export function ExperimentConclusionItem(): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)

    if (!experiment.conclusion) {
        return null
    }

    const config = CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]

    return (
        <Tooltip title={config.description}>
            <span className="flex items-center gap-1.5 font-semibold cursor-default" data-attr="experiment-conclusion">
                <span className={cn('size-2 rounded-full shrink-0', config.color)} />
                <span>{config.title}</span>
            </span>
        </Tooltip>
    )
}
