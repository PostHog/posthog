import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { SPACE_FEED_TYPES, SpaceFeedType } from './spaceFeedEntries'
import { SpaceFeedFilterMenu } from './SpaceFeedFilterMenu'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'

/** The row above the feed: which types show and the filter menu, like PostHog Desktop's. */
export function SpaceFeedControls({ sourceOptions }: { sourceOptions: string[] }): JSX.Element {
    const { types } = useValues(spaceFeedViewLogic)
    const { setTypes } = useActions(spaceFeedViewLogic)

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
            <SpaceFeedFilterMenu sourceOptions={sourceOptions} />
        </div>
    )
}
