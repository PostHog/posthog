import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    SelectTriggerIcon,
} from '@posthog/quill'

import { FunnelLayout } from 'lib/constants'
import { IconFunnelHorizontal, IconFunnelVertical } from 'lib/lemon-ui/icons'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { useFunnelVizType } from './useFunnelVizType'

interface FunnelDisplayChoice {
    key: string
    vizType: VizType
    layout?: FunnelLayout
    label: string
    description: string
    icon: JSX.Element
}

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
    const choices: FunnelDisplayChoice[] = options.flatMap((option): FunnelDisplayChoice[] =>
        option.value === VizType.Steps
            ? [
                  {
                      key: `${option.value}-${FunnelLayout.vertical}`,
                      vizType: option.value,
                      layout: FunnelLayout.vertical,
                      label: `${option.title}, left to right`,
                      description: option.description,
                      icon: <IconFunnelVertical className="text-secondary" />,
                  },
                  {
                      key: `${option.value}-${FunnelLayout.horizontal}`,
                      vizType: option.value,
                      layout: FunnelLayout.horizontal,
                      label: `${option.title}, top to bottom`,
                      description: option.description,
                      icon: <IconFunnelHorizontal className="text-secondary" />,
                  },
              ]
            : [
                  {
                      key: option.value,
                      vizType: option.value,
                      label: option.title,
                      description: option.description,
                      icon: option.icon,
                  },
              ]
    )
    const current = choices.find(
        (choice) => choice.vizType === value && (choice.layout === undefined || choice.layout === layout)
    )

    const choose = (key: string): void => {
        const choice = choices.find((c) => c.key === key)
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
                <span>{current?.label}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup value={current?.key ?? ''} onValueChange={(key) => choose(key as string)}>
                    {choices.map((choice) => (
                        <DropdownMenuRadioItem
                            key={choice.key}
                            value={choice.key}
                            tooltip={choice.description}
                            closeOnClick
                        >
                            {choice.icon}
                            {choice.label}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
