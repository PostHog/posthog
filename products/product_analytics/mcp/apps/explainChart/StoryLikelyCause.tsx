import { type ReactElement } from 'react'

import { Badge, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { StoryConfidence } from './explainChartTypes'
import { StoryMarkedText } from './StoryMarkedText'

const CONFIDENCE: Record<StoryConfidence, { label: string; variant: 'success' | 'info' | 'default'; why: string }> = {
    high: {
        label: 'High confidence',
        variant: 'success',
        why: 'Several independent checks point at this cause.',
    },
    medium: {
        label: 'Medium confidence',
        variant: 'info',
        why: 'One check points at this cause, with nothing to confirm it.',
    },
    low: {
        label: 'A guess',
        variant: 'default',
        why: 'Nothing in the evidence confirms this cause.',
    },
}

export interface StoryLikelyCauseProps {
    cause: string
    confidence: StoryConfidence | null
    confidenceReason: string | null
}

export function StoryLikelyCause({ cause, confidence, confidenceReason }: StoryLikelyCauseProps): ReactElement {
    const badge = confidence ? CONFIDENCE[confidence] : null
    return (
        <div className="flex flex-col gap-1.5" data-attr="explain-chart-cause">
            <div className="flex items-center gap-2">
                <Text size="xs" weight="medium" variant="muted">
                    Likely cause
                </Text>
                {badge && (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    className="cursor-default rounded-md border-0 bg-transparent p-0 focus-visible:outline-2 focus-visible:outline-ring"
                                    data-attr="explain-chart-confidence"
                                />
                            }
                        >
                            <Badge variant={badge.variant}>{badge.label}</Badge>
                        </TooltipTrigger>
                        <TooltipContent side="left">{confidenceReason ?? badge.why}</TooltipContent>
                    </Tooltip>
                )}
            </div>
            <div className="rounded-md bg-muted p-2.5">
                <Text size="sm">
                    <StoryMarkedText text={cause} />
                </Text>
            </div>
        </div>
    )
}
