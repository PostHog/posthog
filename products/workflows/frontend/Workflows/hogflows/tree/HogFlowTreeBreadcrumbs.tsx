import { Fragment } from 'react'

import { IconArrowLeft, IconChevronRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { getWorkflowTreeBranchKey, type WorkflowTreePath } from './workflowTreePresentation'

export function HogFlowTreeBreadcrumbs({
    focusedPath,
    onNavigate,
}: {
    focusedPath: WorkflowTreePath[]
    onNavigate: (depth: number) => void
}): JSX.Element {
    return (
        <div
            // Step cards raise their own content to z-20, so the bar sits above that to cover them while it sticks.
            className="sticky top-0 z-30 -mx-4 -mt-4 mb-3 flex min-w-0 items-center gap-2 border-b bg-background px-4 py-2"
            data-attr="workflow-tree-breadcrumbs"
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconArrowLeft />}
                className="shrink-0"
                onClick={() => onNavigate(focusedPath.length - 1)}
                id="workflow-tree-exit-focus"
                data-attr="workflow-tree-exit-focus"
            >
                Back
            </LemonButton>
            <nav aria-label="Path" className="flex min-w-0 flex-1 flex-wrap items-center gap-x-0.5 gap-y-1">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={() => onNavigate(0)}
                    data-attr="workflow-tree-breadcrumb"
                >
                    Workflow
                </LemonButton>
                {focusedPath.map(({ node, branch }, index) => (
                    <Fragment key={getWorkflowTreeBranchKey(branch.edge)}>
                        <IconChevronRight className="size-3 shrink-0 text-secondary" aria-hidden="true" />
                        {index === focusedPath.length - 1 ? (
                            <span className="min-w-0 truncate px-1 text-xs font-semibold" aria-current="page">
                                {branch.label}
                            </span>
                        ) : (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                className="max-w-full"
                                tooltip={node.action.name}
                                onClick={() => onNavigate(index + 1)}
                                data-attr="workflow-tree-breadcrumb"
                            >
                                <span className="truncate">{branch.label}</span>
                            </LemonButton>
                        )}
                    </Fragment>
                ))}
            </nav>
        </div>
    )
}
