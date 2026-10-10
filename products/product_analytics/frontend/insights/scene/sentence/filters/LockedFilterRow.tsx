import { useActions } from 'kea'

import { Text } from '@posthog/quill'

import { filtersEditorLogic } from './filtersEditorLogic'
import type { LockedFilterRowView } from './filtersEditorLogic'
import { RemoveFilterButton } from './RemoveFilterButton'

export function LockedFilterRow({ row }: { row: LockedFilterRowView }): JSX.Element {
    const { removeRow } = useActions(filtersEditorLogic)

    return (
        <div className="flex items-start gap-2" data-attr="quill-insight-filters-locked-row">
            <div className="flex min-w-0 flex-1 flex-col">
                <Text size="sm" className="wrap-anywhere">
                    {row.description}
                </Text>
                <Text size="xs" variant="muted">
                    You can remove this filter here, but not change it.
                </Text>
            </div>
            <RemoveFilterButton onClick={() => removeRow(row.id)} />
        </div>
    )
}
