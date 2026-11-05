import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
    SelectTriggerIcon,
} from '@posthog/quill'

import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { useFunnelVizType } from './useFunnelVizType'

export function QuillFunnelVizType({
    insightProps,
    disabledReason,
}: Pick<EditorFilterProps, 'insightProps'> & { disabledReason?: string | null }): JSX.Element | null {
    const { value, options, setValue } = useFunnelVizType({ insightProps })
    const current = options.find((option) => option.value === value)

    if (value === VizType.Flow) {
        return null
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
                <span>{current?.title}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuRadioGroup value={value} onValueChange={(next) => setValue(next as VizType)}>
                    {options.map((option) => (
                        <DropdownMenuRadioItem
                            key={option.value}
                            value={option.value}
                            tooltip={option.description}
                            closeOnClick
                        >
                            {option.icon}
                            {option.title}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
