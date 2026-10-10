import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { PropertyPickerPopover } from '../PropertyPickerPopover'
import { FilterRow } from './FilterRow'
import { filtersEditorLogic } from './filtersEditorLogic'
import type { FilterGroupView } from './filtersEditorLogic'
import { LockedFilterRow } from './LockedFilterRow'
import { MatchModeToggle } from './MatchModeToggle'

export interface FilterGroupRowsProps {
    insightProps: InsightLogicProps
    group: FilterGroupView
    emptyText: string
    /** Shown beside the button that adds a filter. */
    addFilterTrailing?: React.ReactNode
}

/** The filters of one group and the button that adds to them. The caller sets the space between the two. */
export function FilterGroupRows({
    insightProps,
    group,
    emptyText,
    addFilterTrailing,
}: FilterGroupRowsProps): JSX.Element {
    const { addFilter, setGroupMatchMode } = useActions(filtersEditorLogic)

    return (
        <>
            {group.rows.length === 0 ? (
                <Text size="sm" variant="muted">
                    {emptyText}
                </Text>
            ) : (
                <div className="flex flex-col gap-2">
                    {group.showMatchMode && (
                        <MatchModeToggle
                            label="How the filters combine"
                            value={group.matchMode}
                            onChange={(matchMode) => setGroupMatchMode(group.id, matchMode)}
                            allLabel="Match all"
                            anyLabel="Match any"
                            allDataAttr="quill-insight-filters-match-all"
                            anyDataAttr="quill-insight-filters-match-any"
                        />
                    )}
                    {group.rows.map((row) =>
                        row.kind === 'filter' ? (
                            <FilterRow key={row.id} insightProps={insightProps} row={row} />
                        ) : (
                            <LockedFilterRow key={row.id} row={row} />
                        )
                    )}
                </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
                <PropertyPickerPopover
                    insightProps={insightProps}
                    onPick={(property) => addFilter(group.id, property)}
                    trigger={(open, toggle) => (
                        <Button
                            variant="outline"
                            aria-expanded={open}
                            onClick={toggle}
                            data-attr="quill-insight-filters-add"
                        >
                            <IconPlus />
                            Add filter
                        </Button>
                    )}
                />
                {addFilterTrailing}
            </div>
        </>
    )
}
