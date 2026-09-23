import type { CSSProperties } from 'react'

import type { HogFlowEdge } from '../types'
import {
    getWaitTimeoutLabel,
    type WorkflowTreeBranch,
    type WorkflowTreeNode,
    type WorkflowTreeSequence,
} from './workflowTree'

export const WORKFLOW_TREE_BRANCH_LIMIT = 6

// pinned: these values travel in the `tree_variant` URL search param, so a shared link opens the same layout
export const WORKFLOW_TREE_LAYOUT_VARIANTS = ['default', 'closed', 'drilldown', 'navigator'] as const
export type WorkflowTreeLayoutVariant = (typeof WORKFLOW_TREE_LAYOUT_VARIANTS)[number]

export interface WorkflowTreePath {
    node: WorkflowTreeNode
    branch: WorkflowTreeBranch
}

export interface WorkflowTreeOccurrence {
    node: WorkflowTreeNode
    path: HogFlowEdge[]
}

export interface WorkflowTreeNodeViewState {
    branchesOpen?: boolean
    collapsedBranches?: Set<string>
    showAllBranches?: boolean
}

export function isWorkflowTreeLayoutVariant(value: unknown): value is WorkflowTreeLayoutVariant {
    return WORKFLOW_TREE_LAYOUT_VARIANTS.includes(value as WorkflowTreeLayoutVariant)
}

export function getWorkflowTreeBranchKey(edge: HogFlowEdge): string {
    return `${edge.from}-${edge.type}-${edge.index ?? 'continue'}`
}

export function getWorkflowTreeBranchIndex(branch: WorkflowTreeBranch, position: number): number | null {
    return branch.edge.type === 'branch' ? (branch.edge.index ?? position) : null
}

export function getWorkflowTreeOccurrenceKey(actionId: string, path: HogFlowEdge[]): string {
    return encodeURIComponent(JSON.stringify([path.map((edge) => [edge.from, edge.type, edge.index]), actionId]))
}

export function getWorkflowTreeStepId(actionId: string, path: HogFlowEdge[]): string {
    return `workflow-tree-step-${actionId}${path.length ? `-${getWorkflowTreeOccurrenceKey(actionId, path)}` : ''}`
}

export function getWorkflowTreePathHeaderId(actionId: string, path: HogFlowEdge[]): string {
    return `workflow-tree-path-${getWorkflowTreeOccurrenceKey(actionId, path)}`
}

export function getWorkflowTreeDefaultCollapsedBranches(
    node: WorkflowTreeNode,
    depth: number,
    variant: WorkflowTreeLayoutVariant
): Set<string> {
    if (variant !== 'closed' || depth === 0) {
        return new Set()
    }
    return new Set(node.branches.map((branch) => getWorkflowTreeBranchKey(branch.edge)))
}

export function getWorkflowTreeBranchBadge(node: WorkflowTreeNode, branchIndex: number | null): string {
    if (node.action.type === 'conditional_branch') {
        return branchIndex === null ? 'Else' : `If #${branchIndex + 1}`
    }
    if (node.action.type === 'wait_until_condition') {
        if (branchIndex !== null) {
            return 'Match'
        }
        return getWaitTimeoutLabel(node.action.config.max_wait_duration) ? 'Timeout' : 'No match'
    }
    if (branchIndex === null) {
        return 'Fallback'
    }
    const percentage =
        node.action.type === 'random_cohort_branch' ? node.action.config.cohorts[branchIndex]?.percentage : undefined
    return percentage !== undefined ? `${percentage}%` : `${branchIndex + 1}`
}

// A condition badge mixes the path color into the text color so that the uppercase label stays
// readable in both themes. Other badges take the path color as is.
export function getWorkflowTreeBranchBadgeStyle(node: WorkflowTreeNode, pathColor: string): CSSProperties {
    return {
        color:
            node.action.type === 'conditional_branch'
                ? `color-mix(in srgb, ${pathColor} 60%, var(--text-3000))`
                : pathColor,
        borderColor: pathColor,
    }
}

export function findWorkflowTreePath(sequence: WorkflowTreeSequence, edges: HogFlowEdge[]): WorkflowTreePath[] {
    const [edge, ...remainingEdges] = edges
    if (!edge) {
        return []
    }
    for (const node of sequence.nodes) {
        for (const branch of node.branches) {
            const path = { node, branch }
            if (branch.edge.from === edge.from && branch.edge.type === edge.type && branch.edge.index === edge.index) {
                if (remainingEdges.length === 0) {
                    return [path]
                }
                const nestedPath = findWorkflowTreePath(branch.sequence, remainingEdges)
                return nestedPath.length ? [path, ...nestedPath] : []
            }
        }
    }
    return []
}

export function getWorkflowTreeContinuationPath(
    tree: WorkflowTreeSequence,
    path: HogFlowEdge[],
    actionId: string
): HogFlowEdge[] {
    for (let depth = path.length; depth > 0; depth--) {
        const ancestorPath = path.slice(0, depth)
        const sequence = findWorkflowTreePath(tree, ancestorPath).at(-1)?.branch.sequence
        if (sequence?.nodes.some((node) => node.action.id === actionId)) {
            return ancestorPath
        }
    }
    return []
}

function collectStepIds(sequence: WorkflowTreeSequence, stepIds: Set<string>): void {
    for (const node of sequence.nodes) {
        stepIds.add(node.action.id)
        for (const branch of node.branches) {
            collectStepIds(branch.sequence, stepIds)
        }
    }
}

export function getWorkflowTreeStepIds(sequence: WorkflowTreeSequence): Set<string> {
    const stepIds = new Set<string>()
    collectStepIds(sequence, stepIds)
    return stepIds
}

export function collectWorkflowTreeBranchingOccurrences(
    sequence: WorkflowTreeSequence,
    path: HogFlowEdge[] = []
): WorkflowTreeOccurrence[] {
    const occurrences: WorkflowTreeOccurrence[] = []
    for (const node of sequence.nodes) {
        if (node.branches.length === 0) {
            continue
        }
        occurrences.push({ node, path })
        for (const branch of node.branches) {
            occurrences.push(...collectWorkflowTreeBranchingOccurrences(branch.sequence, [...path, branch.edge]))
        }
    }
    return occurrences
}

export function getWorkflowTreeNestedPathCount(sequence: WorkflowTreeSequence): number {
    return collectWorkflowTreeBranchingOccurrences(sequence).reduce(
        (total, { node }) => total + node.branches.length,
        0
    )
}

function getPathDestination(sequence: WorkflowTreeSequence): string {
    const lastNode = sequence.nodes.at(-1)
    if (lastNode?.action.type === 'exit') {
        return 'End workflow'
    }
    if (lastNode?.branches.length) {
        const destinations = new Set(lastNode.branches.map((branch) => getPathDestination(branch.sequence)))
        return destinations.size === 1 ? [...destinations][0] : 'Paths have different destinations'
    }
    return 'No next step'
}

export function getWorkflowTreeBranchSummary(node: WorkflowTreeNode, branch: WorkflowTreeBranch): string {
    const stepCount = getWorkflowTreeStepIds(branch.sequence).size
    const pathCount = getWorkflowTreeNestedPathCount(branch.sequence)
    const destination = node.joinAction ? `Continue to: ${node.joinAction.name}` : getPathDestination(branch.sequence)
    return [
        `${stepCount} ${stepCount === 1 ? 'step' : 'steps'}`,
        pathCount > 0 ? `${pathCount} ${pathCount === 1 ? 'path' : 'paths'}` : null,
        destination,
    ]
        .filter((part): part is string => part !== null)
        .join(' · ')
}
