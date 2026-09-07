import { IconRefresh } from '@posthog/icons'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { ErrorFilters } from '../../components/IssueFilters'

interface IssueEventsToolbarProps {
    loading: boolean
    onReload?: () => void
}

export function IssueEventsToolbar({ loading, onReload }: IssueEventsToolbarProps): JSX.Element {
    return (
        <div className="sticky top-0 z-10 shrink-0 border-y border-primary bg-surface-primary">
            <ErrorFilters.Root className="w-full">
                <ErrorFilters.FilterGroup
                    iconOnly
                    renderControls={({ filterPicker, activeFilters }) => (
                        <div className="flex w-full flex-col gap-2 p-2">
                            <div className="flex w-full min-w-0 flex-wrap items-center gap-2">
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="outline"
                                                size="icon"
                                                loading={loading}
                                                aria-label="Reload exceptions"
                                                onClick={onReload}
                                            />
                                        }
                                    >
                                        <IconRefresh />
                                    </TooltipTrigger>
                                    <TooltipContent>Reload exceptions</TooltipContent>
                                </Tooltip>
                                <ErrorFilters.DateRange />
                                <ErrorFilters.Search
                                    className="w-auto min-w-40 flex-1 shrink"
                                    placeholder="Search exceptions"
                                    endAddon={filterPicker}
                                />
                                <div className="shrink-0">
                                    <ErrorFilters.InternalAccounts />
                                </div>
                            </div>
                            {activeFilters}
                        </div>
                    )}
                />
            </ErrorFilters.Root>
        </div>
    )
}
