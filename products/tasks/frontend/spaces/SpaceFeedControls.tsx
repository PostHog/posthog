import { useActions, useValues } from 'kea'

import { IconList, IconStack } from '@posthog/icons'
import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SPACE_FEED_TYPES, SpaceFeedType, SpaceFeedView } from './spaceFeedEntries'
import { SpaceFeedFilterMenu } from './SpaceFeedFilterMenu'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'

const VIEWS: { value: SpaceFeedView; label: string; icon: JSX.Element }[] = [
    { value: 'list', label: 'List', icon: <IconList /> },
    { value: 'cards', label: 'Cards', icon: <IconStack /> },
]

/** The row above the feed: which types show, list or cards, and the filter menu, like PostHog Desktop's. */
export function SpaceFeedControls({ sourceOptions }: { sourceOptions: string[] }): JSX.Element {
    const { types, view } = useValues(spaceFeedViewLogic)
    const { setTypes, setView } = useActions(spaceFeedViewLogic)

    return (
        <div className="mb-1 flex w-full flex-wrap items-center justify-end gap-1">
            <ToggleGroup
                multiple
                value={types}
                onValueChange={(next) => setTypes(next as SpaceFeedType[])}
                aria-label="Types shown"
            >
                {SPACE_FEED_TYPES.map(({ value, label }) => (
                    <ToggleGroupItem key={value} value={value} size="sm" data-attr={`today-space-feed-type-${value}`}>
                        {label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <ToggleGroup
                value={[view]}
                onValueChange={(next) => {
                    const [picked] = next
                    if (picked === 'list' || picked === 'cards') {
                        setView(picked)
                    }
                }}
                spacing={1}
                aria-label="View"
            >
                {VIEWS.map(({ value, label, icon }) => (
                    <Tooltip key={value}>
                        {/* A span carries the tooltip, because the toggle item does not forward its ref, so the toggles are spaced. */}
                        <TooltipTrigger delay={0} render={<span className="flex" />}>
                            <ToggleGroupItem
                                value={value}
                                size="sm"
                                aria-label={`${label} view`}
                                data-attr={`today-space-feed-view-${value}`}
                            >
                                {icon}
                            </ToggleGroupItem>
                        </TooltipTrigger>
                        <TooltipContent>{label}</TooltipContent>
                    </Tooltip>
                ))}
            </ToggleGroup>
            <SpaceFeedFilterMenu sourceOptions={sourceOptions} />
        </div>
    )
}
