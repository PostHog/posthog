import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { getHogFlowBranchColor } from '../HogFlowBranchSelection'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import type { WorkflowTreeOutlineRow as OutlineRow } from './workflowTreeOutline'
import { getWorkflowTreeBranchBadgeStyle } from './workflowTreePresentation'

// Tailwind only emits classes it reads in the source, so the indent per depth is a fixed list.
const INDENT_CLASSES = ['ps-0', 'ps-2', 'ps-4', 'ps-6', 'ps-8', 'ps-10', 'ps-12', 'ps-14', 'ps-16']

export function HogFlowTreeOutlineRow({
    row,
    active,
    onSelect,
}: {
    row: OutlineRow
    active: boolean
    onSelect: (row: OutlineRow) => void
}): JSX.Element {
    const step = useHogFlowStep(row.kind === 'step' ? row.node.action : undefined)
    const pathColor = getHogFlowBranchColor(row.branchIndex)

    return (
        <li className={cn('min-w-0 list-none', INDENT_CLASSES[Math.min(row.depth, INDENT_CLASSES.length - 1)])}>
            <LemonButton
                type="tertiary"
                size="xsmall"
                fullWidth
                active={active}
                aria-current={active ? 'location' : undefined}
                tooltip={
                    row.stepCount === null ? undefined : `${row.stepCount} ${row.stepCount === 1 ? 'step' : 'steps'}`
                }
                icon={
                    row.kind === 'step' ? (
                        <span
                            className="flex size-4 shrink-0 items-center justify-center [&>img]:size-3.5 [&>img]:object-contain [&>svg]:size-3.5"
                            style={step?.color ? { color: step.color } : undefined}
                        >
                            {step?.icon}
                        </span>
                    ) : undefined
                }
                onClick={() => onSelect(row)}
                data-attr={row.kind === 'step' ? 'workflow-tree-outline-step' : 'workflow-tree-outline-path'}
            >
                <span className="flex min-w-0 flex-1 items-center gap-1.5">
                    {row.badge && (
                        <LemonTag
                            size="small"
                            className={cn('shrink-0', row.node.action.type === 'conditional_branch' && 'uppercase')}
                            style={getWorkflowTreeBranchBadgeStyle(row.node, pathColor)}
                        >
                            {row.badge}
                        </LemonTag>
                    )}
                    <span className="min-w-0 flex-1 truncate text-start">{row.label}</span>
                    {row.stepCount !== null && (
                        <span className="shrink-0 text-xs text-secondary" aria-hidden="true">
                            {row.stepCount}
                        </span>
                    )}
                </span>
            </LemonButton>
        </li>
    )
}
