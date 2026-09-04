import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'

export const BRANCHING_ACTION_TYPES = ['conditional_branch', 'random_cohort_branch', 'wait_until_condition'] as const

export interface WorkflowTreeSequence {
    nodes: WorkflowTreeNode[]
    trailingEdge: HogFlowEdge | null
}

export interface WorkflowTreeNode {
    action: HogFlowAction
    incomingEdge: HogFlowEdge | null
    branches: WorkflowTreeBranch[]
    joinActionId: string | null
    joinAction: HogFlowAction | null
    joinEdges: HogFlowEdge[]
}

export interface WorkflowTreeBranch {
    edge: HogFlowEdge
    label: string
    sequence: WorkflowTreeSequence
}

export function isBranchingAction(action: Pick<HogFlowAction, 'type'>): boolean {
    return BRANCHING_ACTION_TYPES.includes(action.type as (typeof BRANCHING_ACTION_TYPES)[number])
}

export function getWorkflowBranchLabel(action: HogFlowAction | undefined, edge: HogFlowEdge): string {
    if (edge.type === 'continue') {
        return 'No match'
    }

    if (!action) {
        return `If condition #${(edge.index ?? 0) + 1} matches`
    }

    switch (action.type) {
        case 'wait_until_condition':
            return action.config.condition?.name || 'If condition matches'
        case 'random_cohort_branch':
            return action.config.cohorts?.[edge.index ?? 0]?.name || `If cohort #${(edge.index ?? 0) + 1} matches`
        case 'conditional_branch':
            return action.config.conditions?.[edge.index ?? 0]?.name || `If condition #${(edge.index ?? 0) + 1} matches`
        default:
            return `If condition #${(edge.index ?? 0) + 1} matches`
    }
}

function intersectSets(sets: Set<string>[]): Set<string> {
    if (sets.length === 0) {
        return new Set()
    }

    return new Set([...sets[0]].filter((value) => sets.slice(1).every((set) => set.has(value))))
}

function setsEqual(left: Set<string>, right: Set<string>): boolean {
    return left.size === right.size && [...left].every((value) => right.has(value))
}

function buildPostDominators(
    actionIds: string[],
    outgoingEdgesByActionId: Map<string, HogFlowEdge[]>
): Map<string, Set<string>> {
    const allActionIds = new Set(actionIds)
    const postDominators = new Map(
        actionIds.map((actionId) => [
            actionId,
            outgoingEdgesByActionId.get(actionId)?.length ? new Set(allActionIds) : new Set([actionId]),
        ])
    )

    for (let pass = 0; pass < actionIds.length * actionIds.length; pass++) {
        let changed = false

        for (const actionId of actionIds) {
            const successors = (outgoingEdgesByActionId.get(actionId) ?? [])
                .map((edge) => postDominators.get(edge.to))
                .filter((set): set is Set<string> => !!set)
            const next = new Set([actionId, ...intersectSets(successors)])

            if (!setsEqual(next, postDominators.get(actionId) ?? new Set())) {
                postDominators.set(actionId, next)
                changed = true
            }
        }

        if (!changed) {
            break
        }
    }

    return postDominators
}

function distancesFrom(
    startActionId: string,
    outgoingEdgesByActionId: Map<string, HogFlowEdge[]>
): Map<string, number> {
    const distances = new Map([[startActionId, 0]])
    const queue = [startActionId]

    for (let index = 0; index < queue.length; index++) {
        const actionId = queue[index]
        const distance = distances.get(actionId) ?? 0

        for (const edge of outgoingEdgesByActionId.get(actionId) ?? []) {
            if (!distances.has(edge.to)) {
                distances.set(edge.to, distance + 1)
                queue.push(edge.to)
            }
        }
    }

    return distances
}

function findBranchJoinActionId(
    actionId: string,
    edges: HogFlowEdge[],
    outgoingEdgesByActionId: Map<string, HogFlowEdge[]>,
    postDominatorsByActionId: Map<string, Set<string>>,
    actionOrder: Map<string, number>
): string | null {
    const targetIds = [...new Set(edges.map((edge) => edge.to))]
    const candidates = intersectSets(
        targetIds.map((targetId) => postDominatorsByActionId.get(targetId) ?? new Set<string>())
    )
    candidates.delete(actionId)

    const distances = targetIds.map((targetId) => distancesFrom(targetId, outgoingEdgesByActionId))

    return (
        [...candidates].sort((left, right) => {
            const leftDistances = distances.map((map) => map.get(left) ?? Number.POSITIVE_INFINITY)
            const rightDistances = distances.map((map) => map.get(right) ?? Number.POSITIVE_INFINITY)
            const maxDifference = Math.max(...leftDistances) - Math.max(...rightDistances)
            const totalDifference =
                leftDistances.reduce((total, distance) => total + distance, 0) -
                rightDistances.reduce((total, distance) => total + distance, 0)

            return maxDifference || totalDifference || (actionOrder.get(left) ?? 0) - (actionOrder.get(right) ?? 0)
        })[0] ?? null
    )
}

function collectBranchJoinEdges(
    sequence: WorkflowTreeSequence,
    joinActionId: string,
    joinEdges: Map<string, HogFlowEdge>
): void {
    if (sequence.trailingEdge?.to === joinActionId) {
        const edge = sequence.trailingEdge
        joinEdges.set(`${edge.from}:${edge.to}:${edge.type}:${edge.index ?? ''}`, edge)
    }

    for (const node of sequence.nodes) {
        for (const branch of node.branches) {
            collectBranchJoinEdges(branch.sequence, joinActionId, joinEdges)
        }
    }
}

export function buildWorkflowTree(workflow: Pick<HogFlow, 'actions' | 'edges'>): WorkflowTreeSequence {
    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const actionOrder = new Map(workflow.actions.map((action, index) => [action.id, index]))
    const outgoingEdgesByActionId = new Map<string, HogFlowEdge[]>()

    for (const edge of workflow.edges) {
        if (!actionsById.has(edge.from) || !actionsById.has(edge.to)) {
            continue
        }
        outgoingEdgesByActionId.set(edge.from, [...(outgoingEdgesByActionId.get(edge.from) ?? []), edge])
    }

    for (const edges of outgoingEdgesByActionId.values()) {
        edges.sort((left, right) => {
            if (left.type !== right.type) {
                return left.type === 'branch' ? -1 : 1
            }
            return (left.index ?? Number.POSITIVE_INFINITY) - (right.index ?? Number.POSITIVE_INFINITY)
        })
    }

    const postDominatorsByActionId = buildPostDominators([...actionsById.keys()], outgoingEdgesByActionId)

    const buildSequence = (
        startActionId: string | undefined,
        stopActionId: string | null,
        incomingEdge: HogFlowEdge | null,
        ancestors: Set<string>
    ): WorkflowTreeSequence => {
        const nodes: WorkflowTreeNode[] = []
        let actionId = startActionId
        let edgeIntoAction = incomingEdge

        while (actionId && actionId !== stopActionId && !ancestors.has(actionId)) {
            const action = actionsById.get(actionId)
            if (!action) {
                break
            }

            ancestors.add(actionId)
            const outgoingEdges = outgoingEdgesByActionId.get(actionId) ?? []
            const node: WorkflowTreeNode = {
                action,
                incomingEdge: edgeIntoAction,
                branches: [],
                joinActionId: null,
                joinAction: null,
                joinEdges: [],
            }

            if (outgoingEdges.length <= 1) {
                nodes.push(node)
                edgeIntoAction = outgoingEdges[0] ?? null
                actionId = outgoingEdges[0]?.to
                continue
            }

            const joinActionId = findBranchJoinActionId(
                actionId,
                outgoingEdges,
                outgoingEdgesByActionId,
                postDominatorsByActionId,
                actionOrder
            )
            node.joinActionId = joinActionId
            node.joinAction = joinActionId ? (actionsById.get(joinActionId) ?? null) : null
            node.branches = outgoingEdges.map((edge) => ({
                edge,
                label: getWorkflowBranchLabel(action, edge),
                sequence: buildSequence(edge.to, joinActionId, edge, new Set(ancestors)),
            }))
            if (joinActionId) {
                const joinEdges = new Map<string, HogFlowEdge>()
                for (const branch of node.branches) {
                    collectBranchJoinEdges(branch.sequence, joinActionId, joinEdges)
                }
                node.joinEdges = [...joinEdges.values()]
            }
            nodes.push(node)

            if (!joinActionId) {
                return { nodes, trailingEdge: null }
            }

            actionId = joinActionId
            edgeIntoAction = null
        }

        return { nodes, trailingEdge: actionId === stopActionId ? edgeIntoAction : null }
    }

    const trigger = workflow.actions.find((action) => action.type === 'trigger') ?? workflow.actions[0]
    return buildSequence(trigger?.id, null, null, new Set())
}

export function countWorkflowTreeNodes(sequence: WorkflowTreeSequence): number {
    return sequence.nodes.reduce(
        (total, node) =>
            total +
            1 +
            node.branches.reduce((branchTotal, branch) => branchTotal + countWorkflowTreeNodes(branch.sequence), 0),
        0
    )
}

function findWorkflowTreeNode(sequence: WorkflowTreeSequence, actionId: string): WorkflowTreeNode | null {
    for (const node of sequence.nodes) {
        if (node.action.id === actionId) {
            return node
        }

        for (const branch of node.branches) {
            const branchNode = findWorkflowTreeNode(branch.sequence, actionId)
            if (branchNode) {
                return branchNode
            }
        }
    }

    return null
}

function collectWorkflowTreeActionIds(sequence: WorkflowTreeSequence, actionIds: Set<string>): void {
    for (const node of sequence.nodes) {
        actionIds.add(node.action.id)
        for (const branch of node.branches) {
            collectWorkflowTreeActionIds(branch.sequence, actionIds)
        }
    }
}

export function computeMoveTreeBranchEdges(
    workflow: Pick<HogFlow, 'actions' | 'edges'>,
    movingActionId: string,
    targetEdge: HogFlowEdge,
    isBranchJoinDropzone: boolean,
    joinEdges?: HogFlowEdge[]
): HogFlow['edges'] | null {
    const branchNode = findWorkflowTreeNode(buildWorkflowTree(workflow), movingActionId)
    const joinActionId = branchNode?.joinActionId

    if (!branchNode || !joinActionId) {
        return null
    }

    const movedActionIds = new Set([movingActionId])
    for (const branch of branchNode.branches) {
        collectWorkflowTreeActionIds(branch.sequence, movedActionIds)
    }

    if (movedActionIds.has(targetEdge.from) || movedActionIds.has(targetEdge.to)) {
        return null
    }

    const terminalEdges = workflow.edges.filter((edge) => movedActionIds.has(edge.from) && edge.to === joinActionId)
    if (terminalEdges.length === 0 || !workflow.edges.some((edge) => edge.to === movingActionId)) {
        return null
    }

    let newEdges = workflow.edges.map((edge) => (edge.to === movingActionId ? { ...edge, to: joinActionId } : edge))

    const targetEdgeIndexes = isBranchJoinDropzone
        ? newEdges
              .map((edge, index) => ({ edge, index }))
              .filter(({ edge }) => {
                  if (movedActionIds.has(edge.from)) {
                      return false
                  }

                  if (joinEdges) {
                      return joinEdges.some(
                          (joinEdge) =>
                              edge.from === joinEdge.from &&
                              edge.to === joinEdge.to &&
                              edge.type === joinEdge.type &&
                              edge.index === joinEdge.index
                      )
                  }

                  return edge.to === targetEdge.to
              })
              .map(({ index }) => index)
        : [
              newEdges.findIndex(
                  (edge) =>
                      edge.from === targetEdge.from && edge.type === targetEdge.type && edge.index === targetEdge.index
              ),
          ]

    if (targetEdgeIndexes.length === 0 || targetEdgeIndexes.includes(-1)) {
        return null
    }

    const edgesToSplit = targetEdgeIndexes.map((index) => newEdges[index])
    const insertionTarget = edgesToSplit[0].to
    targetEdgeIndexes.sort((left, right) => right - left).forEach((index) => newEdges.splice(index, 1))

    const terminalEdgeSet = new Set(terminalEdges)
    newEdges = newEdges.map((edge) => (terminalEdgeSet.has(edge) ? { ...edge, to: insertionTarget } : edge))
    newEdges.push(...edgesToSplit.map((edge) => ({ ...edge, to: movingActionId })))

    return newEdges
}
