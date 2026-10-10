import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import { poeFilterLogic } from 'scenes/insights/EditorFilters/poeFilterLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { InsightLogicProps } from '~/types'

/** The rarely used options that change how the insight is calculated. */
export function InsightAdvancedMenu({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries, samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const isSampled = samplingFactor != null && samplingFactor < 1

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label="More options"
                        data-attr="quill-insight-advanced-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-w-80 min-w-72">
                <DropdownMenuLabel>Advanced</DropdownMenuLabel>
                <DropdownMenuCheckboxItem
                    checked={!!poeMode}
                    disabled={hasDataWarehouseSeries}
                    onCheckedChange={(checked: boolean) =>
                        setPoeMode(checked ? 'person_id_override_properties_joined' : null)
                    }
                    className="h-auto items-start py-1.5 whitespace-normal"
                    data-attr="quill-insight-advanced-person-properties"
                >
                    <ItemContent variant="menuItem">
                        <ItemTitle>Use each person's latest properties</ItemTitle>
                        <ItemDescription>
                            {hasDataWarehouseSeries
                                ? 'Data warehouse insights always use the latest properties.'
                                : 'By default an insight uses the properties a person had at the time of the event. This can make queries slower.'}
                        </ItemDescription>
                    </ItemContent>
                </DropdownMenuCheckboxItem>
                {isSampled && (
                    <DropdownMenuItem
                        onClick={() => updateQuerySource({ samplingFactor: null })}
                        data-attr="quill-insight-advanced-sampling-off"
                    >
                        {`Turn off sampling (now ${Math.round(samplingFactor * 100)}%)`}
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
