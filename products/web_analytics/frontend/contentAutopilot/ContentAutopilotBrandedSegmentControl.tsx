import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { AiVisibilityFilterTab } from './aiVisibilityFilters'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

export const ContentAutopilotBrandedSegmentControl = ({ tab }: { tab: AiVisibilityFilterTab }): JSX.Element => {
    const { brandedSegment } = useValues(contentAutopilotFiltersLogic)
    const { setBrandedSegment } = useActions(contentAutopilotFiltersLogic)

    return (
        <LemonSegmentedButton
            size="small"
            value={brandedSegment}
            onChange={(segment) => setBrandedSegment(segment, tab)}
            options={[
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
            ]}
            data-attr={`content-autopilot-${tab}-branded-segment`}
        />
    )
}
