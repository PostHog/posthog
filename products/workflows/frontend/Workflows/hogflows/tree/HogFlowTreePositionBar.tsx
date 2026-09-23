import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'

import { IconChevronRight, IconListTree } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { cn } from 'lib/utils/css-classes'

import { getWorkflowTreeBranchKey, type WorkflowTreePath } from './workflowTreePresentation'

export function HogFlowTreePositionBar({
    ancestors,
    onSelectAncestor,
    renderOutline,
}: {
    ancestors: WorkflowTreePath[]
    onSelectAncestor: (depth: number) => void
    renderOutline: (close: () => void) => ReactNode
}): JSX.Element {
    const [outlineOpen, setOutlineOpen] = useState(false)
    const closeOutline = (): void => setOutlineOpen(false)

    return (
        <div
            className={cn(
                // Step cards raise their own content to z-20, so the bar sits above that to cover them while it sticks.
                'sticky top-0 z-30 -mx-4 -mt-4 mb-2 flex min-w-0 items-center gap-2 border-b bg-background px-4 py-1',
                ancestors.length === 0 && '@min-[84rem]/workflow-editor:hidden'
            )}
            data-attr="workflow-tree-position-bar"
        >
            <Popover
                visible={outlineOpen}
                onClickOutside={closeOutline}
                placement="bottom-start"
                overlay={<div className="flex max-h-96 w-72 flex-col">{renderOutline(closeOutline)}</div>}
            >
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconListTree />}
                    className="shrink-0 @min-[84rem]/workflow-editor:hidden"
                    aria-expanded={outlineOpen}
                    onClick={() => setOutlineOpen((open) => !open)}
                    data-attr="workflow-tree-outline-toggle"
                >
                    Outline
                </LemonButton>
            </Popover>
            {ancestors.length > 0 && (
                <nav aria-label="Current path" className="flex min-w-0 flex-1 flex-wrap items-center gap-x-0.5 gap-y-1">
                    {ancestors.map(({ node, branch }, index) => (
                        <Fragment key={getWorkflowTreeBranchKey(branch.edge)}>
                            {index > 0 && (
                                <IconChevronRight className="size-3 shrink-0 text-secondary" aria-hidden="true" />
                            )}
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                className="max-w-full"
                                tooltip={node.action.name}
                                onClick={() => onSelectAncestor(index)}
                                data-attr="workflow-tree-position-crumb"
                            >
                                <span className="truncate">{branch.label}</span>
                            </LemonButton>
                        </Fragment>
                    ))}
                </nav>
            )}
        </div>
    )
}
