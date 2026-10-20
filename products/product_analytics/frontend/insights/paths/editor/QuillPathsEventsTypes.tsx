import { useActions, useValues } from 'kea'

import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
    SelectTriggerIcon,
} from '@posthog/quill'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { humanizePathsEventTypes } from 'scenes/insights/utils'

import { EditorFilterProps, PathType } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

const PATH_TYPE_OPTIONS = [
    { type: PathType.PageView, label: 'Page views' },
    { type: PathType.Screen, label: 'Screen views' },
    { type: PathType.CustomEvent, label: 'Custom event' },
    { type: PathType.HogQL, label: 'SQL expression' },
]

export function QuillPathsEventsTypes({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const includeEventTypes = pathsFilter?.includeEventTypes ?? []

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" left className="w-full" />}>
                <span className="min-w-0 flex-1 truncate text-start">
                    {capitalizeFirstLetter(humanizePathsEventTypes(pathsFilter?.includeEventTypes).join(' & '))}
                </span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {PATH_TYPE_OPTIONS.map(({ type, label }) => {
                    const selected = includeEventTypes.includes(type)
                    return (
                        <DropdownMenuCheckboxItem
                            key={type}
                            data-attr={`path-type-${type}`}
                            checked={selected}
                            onCheckedChange={() =>
                                updateInsightFilter({
                                    includeEventTypes: selected
                                        ? includeEventTypes.filter((t) => t !== type)
                                        : [...includeEventTypes, type],
                                })
                            }
                            // At least one event type must stay selected
                            disabled={selected && includeEventTypes.length === 1}
                            closeOnClick={false}
                        >
                            {label}
                        </DropdownMenuCheckboxItem>
                    )
                })}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
