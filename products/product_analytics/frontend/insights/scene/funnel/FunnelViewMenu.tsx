import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuTrigger } from '@posthog/quill'

import { FunnelVizType } from '~/types'
import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { insightSentenceLogic } from '../sentence/insightSentenceLogic'

const VIEWS: { value: FunnelVizType; label: string }[] = [
    { value: FunnelVizType.Steps, label: 'Conversion steps' },
    { value: FunnelVizType.Trends, label: 'Conversion over time' },
    { value: FunnelVizType.TimeToConvert, label: 'Time to convert' },
]

export function FunnelViewMenu({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { funnelsQuery } = useValues(insightSentenceLogic(insightProps))
    const { changeFunnelView } = useActions(insightSentenceLogic(insightProps))

    if (!funnelsQuery) {
        return null
    }

    const current = VIEWS.find((view) => view.value === funnelsQuery.funnelsFilter?.funnelVizType) ?? VIEWS[0]

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" size="sm" data-attr="quill-insight-funnel-view" />}>
                {current.label}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuRadioGroup
                    value={current.value}
                    onValueChange={(value: FunnelVizType) => changeFunnelView(value)}
                >
                    {VIEWS.map((view) => (
                        <MenuChoiceItem key={view.value} value={view.value}>
                            {view.label}
                        </MenuChoiceItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
