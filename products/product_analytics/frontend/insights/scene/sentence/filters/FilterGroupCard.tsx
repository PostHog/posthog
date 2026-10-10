import { useActions } from 'kea'
import { useId } from 'react'

import { Button, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { FilterGroupRows } from './FilterGroupRows'
import { filtersEditorLogic } from './filtersEditorLogic'
import type { FilterGroupView } from './filtersEditorLogic'

/** One group of filters in a frame of its own, for an editor that shows more than one group. */
export function FilterGroupCard({
    insightProps,
    group,
}: {
    insightProps: InsightLogicProps
    group: FilterGroupView
}): JSX.Element {
    const { removeGroup } = useActions(filtersEditorLogic)
    const titleId = useId()

    return (
        <div
            role="group"
            aria-labelledby={titleId}
            className="flex flex-col gap-2 rounded-(--radius-md) border border-(--border) p-2"
            data-attr="quill-insight-filters-group"
        >
            <div className="flex items-center justify-between gap-2">
                <Text id={titleId} size="xs" weight="medium" variant="muted">
                    {group.title}
                </Text>
                <Button
                    variant="link-muted"
                    size="sm"
                    aria-label={`Remove ${group.title.toLowerCase()}`}
                    onClick={() => removeGroup(group.id)}
                    data-attr="quill-insight-filters-remove-group"
                >
                    Remove group
                </Button>
            </div>
            <FilterGroupRows insightProps={insightProps} group={group} emptyText="No filters in this group yet." />
        </div>
    )
}
