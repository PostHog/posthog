import { useActions, useValues } from 'kea'

import { Button, ItemGroup, Skeleton, Text, TooltipProvider } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { BuiltInFilterRow } from './BuiltInFilterRow'
import { builtInFiltersLogic } from './builtInFiltersLogic'

export function BuiltInFilters(): JSX.Element {
    const { builtInFilters, builtInFiltersLoadFailed, pendingKeys } = useValues(builtInFiltersLogic)
    const { loadBuiltInFilters, setFilterEnabled } = useActions(builtInFiltersLogic)
    const editDisabledReason = errorTrackingEditAccessDisabledReason()

    return (
        <div data-quill>
            <TooltipProvider>
                {builtInFiltersLoadFailed ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <Text size="xs" className="m-0">
                            Couldn't load the automatic suppression rules.
                        </Text>
                        <Button variant="outline" onClick={() => loadBuiltInFilters()}>
                            Try again
                        </Button>
                    </div>
                ) : builtInFilters === null ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-14 w-full" />
                        <Skeleton className="h-14 w-full" />
                        <Skeleton className="h-14 w-full" />
                    </div>
                ) : (
                    <ItemGroup combined>
                        {builtInFilters.map((filter) => (
                            <BuiltInFilterRow
                                key={filter.key}
                                filter={filter}
                                saving={pendingKeys.includes(filter.key)}
                                editDisabledReason={editDisabledReason}
                                onSetEnabled={(enabled) => setFilterEnabled(filter.key, enabled)}
                            />
                        ))}
                    </ItemGroup>
                )}
            </TooltipProvider>
        </div>
    )
}
