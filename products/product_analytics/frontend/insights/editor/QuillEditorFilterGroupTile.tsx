import { Card, Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger } from '@posthog/quill'

import { slugify } from 'lib/utils/strings'

import type { EditorFilterGroupTileProps } from './EditorFilterGroupTile'
import { captureEditorGroupToggle } from './editorFilterUtils'
import { QuillEditorFilterItems } from './QuillEditorFilterItems'
import { useEditorGroupExpansion } from './useEditorGroupExpansion'

export function QuillEditorFilterGroupTile({
    insightProps,
    editorFilterGroup,
    queryKind,
}: EditorFilterGroupTileProps): JSX.Element {
    const { title, defaultExpanded, editorFilters, collapsedSummary, headerExtra } = editorFilterGroup
    const [isRowExpanded, setIsRowExpanded, isExpandable] = useEditorGroupExpansion(defaultExpanded, !!collapsedSummary)

    const items = (
        <div className="flex min-w-0 flex-col gap-3 px-3 pt-1 pb-3">
            <QuillEditorFilterItems editorFilters={editorFilters} insightProps={insightProps} />
        </div>
    )

    if (!isExpandable) {
        return (
            <Card size="sm" className="m-px min-w-0 gap-0 py-0">
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                    <span className="font-semibold">{title}</span>
                    {headerExtra}
                </div>
                {items}
            </Card>
        )
    }

    return (
        <Card size="sm" className="m-px min-w-0 gap-0 py-0">
            <Collapsible
                variant="folder"
                open={isRowExpanded}
                onOpenChange={(open) => {
                    setIsRowExpanded(open)
                    captureEditorGroupToggle(title, open, queryKind)
                }}
            >
                <CollapsibleHeader className="gap-0">
                    <CollapsibleTrigger
                        className="h-10 w-auto min-w-0 flex-1 rounded-none ps-2 pe-3"
                        data-attr={'editor-filter-group-collapse-' + slugify(title)}
                    >
                        <span className="shrink-0 font-semibold">{title}</span>
                        {!isRowExpanded && collapsedSummary && (
                            <span className="truncate text-muted-foreground">{collapsedSummary}</span>
                        )}
                    </CollapsibleTrigger>
                    {headerExtra && <div className="shrink-0 pe-2">{headerExtra}</div>}
                </CollapsibleHeader>
                <CollapsibleContent keepMounted className="p-0">
                    {items}
                </CollapsibleContent>
            </Collapsible>
        </Card>
    )
}
