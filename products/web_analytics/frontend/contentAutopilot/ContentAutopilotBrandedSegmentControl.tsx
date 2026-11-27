import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { AiVisibilityFilterTab } from './aiVisibilityFilters'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

const SEGMENTS: { value: BrandedSegmentEnumApi; label: string; tooltip: string }[] = [
    {
        value: BrandedSegmentEnumApi.NonBranded,
        label: 'Non-branded',
        tooltip: "Prompts that don't name your brand. Use them to judge how visible you are.",
    },
    {
        value: BrandedSegmentEnumApi.Branded,
        label: 'Branded',
        tooltip: 'Prompts that name your brand. Answers to them almost always mention you.',
    },
    { value: BrandedSegmentEnumApi.All, label: 'All', tooltip: 'Every prompt.' },
]

export const ContentAutopilotBrandedSegmentControl = ({ tab }: { tab: AiVisibilityFilterTab }): JSX.Element => {
    const { brandedSegment } = useValues(contentAutopilotFiltersLogic)
    const { setBrandedSegment } = useActions(contentAutopilotFiltersLogic)

    return (
        <ToggleGroup
            variant="outline"
            aria-label="Branded prompts"
            value={[brandedSegment]}
            onValueChange={(next: string[]) => {
                // Clicking the chosen segment again empties the group, which keeps the current segment.
                if (next[0]) {
                    setBrandedSegment(next[0] as BrandedSegmentEnumApi, tab)
                }
            }}
            data-attr={`content-autopilot-${tab}-branded-segment`}
        >
            {SEGMENTS.map(({ value, label, tooltip }) => (
                <Tooltip key={value}>
                    <TooltipTrigger render={<ToggleGroupItem value={value} />}>{label}</TooltipTrigger>
                    <TooltipContent>{tooltip}</TooltipContent>
                </Tooltip>
            ))}
        </ToggleGroup>
    )
}
