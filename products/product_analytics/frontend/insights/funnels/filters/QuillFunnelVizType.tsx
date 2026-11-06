import { useActions, useValues } from 'kea'

import { IconFunnels, IconGraph, IconLineGraph } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    SelectTriggerIcon,
} from '@posthog/quill'

import { FunnelLayout } from 'lib/constants'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { useFunnelVizType } from './useFunnelVizType'

interface FunnelDisplayChoice {
    key: string
    vizType: VizType
    layout?: FunnelLayout
    label: string
    buttonLabel: string
    icon: JSX.Element
}

const CHOICE_GROUPS: { title: string; choices: FunnelDisplayChoice[] }[] = [
    {
        title: 'Steps',
        choices: [
            {
                key: 'steps-vertical',
                vizType: VizType.Steps,
                layout: FunnelLayout.vertical,
                label: 'Left to right',
                buttonLabel: 'Steps, left to right',
                icon: <IconFunnels className="-rotate-90" />,
            },
            {
                key: 'steps-horizontal',
                vizType: VizType.Steps,
                layout: FunnelLayout.horizontal,
                label: 'Top to bottom',
                buttonLabel: 'Steps, top to bottom',
                icon: <IconFunnels />,
            },
        ],
    },
    {
        title: 'Over time',
        choices: [
            {
                key: 'time-to-convert',
                vizType: VizType.TimeToConvert,
                label: 'Time to convert',
                buttonLabel: 'Time to convert',
                icon: <IconGraph />,
            },
            {
                key: 'trends',
                vizType: VizType.Trends,
                label: 'Conversion rate',
                buttonLabel: 'Conversion rate',
                icon: <IconLineGraph />,
            },
        ],
    },
]

const CHOICES = CHOICE_GROUPS.flatMap((group) => group.choices)

export function QuillFunnelVizType({
    insightProps,
    disabledReason,
}: Pick<EditorFilterProps, 'insightProps'> & { disabledReason?: string | null }): JSX.Element | null {
    const { value, options } = useFunnelVizType({ insightProps })
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    if (value === VizType.Flow) {
        return null
    }

    const layout = funnelsFilter?.layout || FunnelLayout.vertical
    const current = CHOICES.find(
        (choice) => choice.vizType === value && (choice.layout === undefined || choice.layout === layout)
    )
    const descriptionFor = (vizType: VizType): string | undefined =>
        options.find((option) => option.value === vizType)?.description

    const choose = (key: string): void => {
        const choice = CHOICES.find((c) => c.key === key)
        if (!choice) {
            return
        }
        const changes: Partial<FunnelsFilter> = {}
        if (choice.vizType !== value) {
            changes.funnelVizType = choice.vizType
        }
        if (choice.layout && choice.layout !== layout) {
            changes.layout = choice.layout
        }
        if (Object.keys(changes).length > 0) {
            updateInsightFilter(changes)
        }
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                disabled={!!disabledReason}
                render={
                    <Button variant="outline" left disabledReason={disabledReason} data-attr="funnel-viz-type-select" />
                }
            >
                {current?.icon}
                <span>{current?.buttonLabel}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup value={current?.key ?? ''} onValueChange={(key) => choose(key as string)}>
                    {CHOICE_GROUPS.map((group) => (
                        <DropdownMenuGroup key={group.title}>
                            <DropdownMenuLabel>{group.title}</DropdownMenuLabel>
                            {group.choices.map((choice) => (
                                <DropdownMenuRadioItem
                                    key={choice.key}
                                    value={choice.key}
                                    tooltip={descriptionFor(choice.vizType)}
                                    closeOnClick
                                >
                                    {choice.icon}
                                    {choice.label}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuGroup>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
