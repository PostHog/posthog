/**
 * Pure planning logic for notebooks-run-all-cells: what order to run a notebook's cells in,
 * which variable values to bind, and where a resumed pass picks up. No I/O, so every rule
 * here is unit-testable without a notebook.
 */

import type { Schemas } from '@/api/generated'

import type { CellTagBlock } from './cellTags'

/** Mirrors MAX_VARIABLES_PER_NOTEBOOK in sql_v2_serializers.py. */
export const MAX_NOTEBOOK_VARIABLES = 10

export interface PlannedCell {
    node_id: string
    node_type: 'hogql' | 'python'
    code: string
    output_name: string
    dataframe_name?: string
}

export interface RunPlan {
    plan: PlannedCell[]
    /** Cells on or downstream of a dependency cycle, appended in document order. */
    cycleNodeIds: string[]
}

/**
 * Execution order: a topological sort of the server's dependency edges, tie-broken by
 * document order.
 *
 * Document order alone is wrong for a legal notebook, because the kernel namespace is not
 * positional — a cell near the top may read a dataframe a cell near the bottom produces, and
 * running it first would silently bind the previous pass's frame and still report success.
 *
 * The edges come from the state endpoint rather than from a scan of the code here: the server
 * parses the HogQL AST and analyzes Python globals, so a dataframe name inside a comment or a
 * string literal does not invent an edge. A false edge would reorder the run, or manufacture a
 * cycle, so ordering takes the better graph.
 *
 * A linear notebook therefore keeps exactly its document order.
 */
export function buildRunPlan(stateCells: Schemas.NotebookCellState[], markdownCells: CellTagBlock[]): RunPlan {
    const byNode = new Map(markdownCells.filter((cell) => cell.nodeId).map((cell) => [cell.nodeId!, cell]))

    const runnable = stateCells.filter((cell) => {
        if (cell.cell_type !== 'sql' && cell.cell_type !== 'python') {
            return false
        }
        // A cell the document no longer holds cannot be dispatched: code and dataframe name
        // come from the markdown, since the state endpoint truncates long code.
        const block = byNode.get(cell.node_id)
        return !!block && !!block.code.trim()
    })

    const docIndex = new Map(runnable.map((cell, index) => [cell.node_id, index]))
    const indegree = new Map<string, number>()
    for (const cell of runnable) {
        // Edges to cells outside the plan are ignored — nothing in this pass will satisfy them.
        indegree.set(cell.node_id, cell.depends_on.filter((upstream) => docIndex.has(upstream)).length)
    }

    const ready = runnable.filter((cell) => indegree.get(cell.node_id) === 0).map((cell) => cell.node_id)
    const byNodeState = new Map(runnable.map((cell) => [cell.node_id, cell]))
    const ordered: string[] = []
    while (ready.length) {
        // Lowest document index among the ready set, so ties read top to bottom.
        ready.sort((left, right) => docIndex.get(left)! - docIndex.get(right)!)
        const nodeId = ready.shift()!
        ordered.push(nodeId)
        for (const dependent of byNodeState.get(nodeId)!.dependents) {
            if (!indegree.has(dependent)) {
                continue
            }
            const remaining = indegree.get(dependent)! - 1
            indegree.set(dependent, remaining)
            if (remaining === 0) {
                ready.push(dependent)
            }
        }
    }

    // Kahn's residue is exactly the cells on or downstream of a cycle. A cycle is reachable in
    // a real notebook, so run those in document order rather than refusing the whole pass.
    const placed = new Set(ordered)
    const cycleNodeIds = runnable.map((cell) => cell.node_id).filter((nodeId) => !placed.has(nodeId))

    const plan = [...ordered, ...cycleNodeIds].map((nodeId) => {
        const block = byNode.get(nodeId)!
        return {
            node_id: nodeId,
            node_type: (block.tagName === 'SQLV2' ? 'hogql' : 'python') as 'hogql' | 'python',
            code: block.code,
            output_name: block.returnVariable,
            ...(block.returnVariable ? { dataframe_name: block.returnVariable } : {}),
        }
    })

    return { plan, cycleNodeIds }
}

/**
 * Names in `candidates` that look like a typo of `name`.
 *
 * Mirrors the shape of `get_close_matches(name, candidates, n=3, cutoff=0.6)` in
 * sql_v2_variables.py, so an agent sees the same affordance from this tool and from a failed
 * dispatch. The similarity metric is normalized edit distance rather than Python's
 * SequenceMatcher ratio, so ranking can differ on unusual inputs — it only orders a suggestion
 * list, so the approximation is not worth a port of difflib.
 */
export function closeNames(name: string, candidates: string[], limit = 3, cutoff = 0.6): string[] {
    const target = name.toLowerCase()
    return candidates
        .map((candidate) => ({ candidate, score: similarity(target, candidate.toLowerCase()) }))
        .filter((entry) => entry.score >= cutoff)
        .sort((left, right) => right.score - left.score || left.candidate.localeCompare(right.candidate))
        .slice(0, limit)
        .map((entry) => entry.candidate)
}

function similarity(left: string, right: string): number {
    const longest = Math.max(left.length, right.length)
    return longest === 0 ? 1 : 1 - editDistance(left, right) / longest
}

function editDistance(left: string, right: string): number {
    let previous = Array.from({ length: right.length + 1 }, (_, index) => index)
    for (let i = 1; i <= left.length; i++) {
        const current = [i]
        for (let j = 1; j <= right.length; j++) {
            current[j] = Math.min(
                previous[j]! + 1,
                current[j - 1]! + 1,
                previous[j - 1]! + (left[i - 1] === right[j - 1] ? 0 : 1)
            )
        }
        previous = current
    }
    return previous[right.length]!
}

export interface VariablePatchEntry {
    name: string
    value: string | number | boolean | null
    type?: 'string' | 'number' | 'boolean' | 'date'
}

/**
 * Merge a by-name patch into the notebook's declared variables, keeping every value the
 * caller did not name.
 *
 * A patch cannot add, remove, or rename — that is notebooks-set-variables' job, and it owns the
 * collision checks that only matter when the declaration set changes. Restricting this to
 * values means a caller changing one variable can never drop the other nine, which whole-list
 * replacement makes easy to do by accident.
 */
export function applyVariablePatch(
    declared: Schemas.NotebookVariable[],
    patch: VariablePatchEntry[]
): Schemas.NotebookVariable[] {
    const repeated = patch.map((entry) => entry.name).filter((name, index, names) => names.indexOf(name) !== index)
    if (repeated.length) {
        throw new Error(`Variable names must be unique. Repeated: ${[...new Set(repeated)].join(', ')}.`)
    }

    const declaredNames = declared.map((variable) => variable.name)
    const unknown = patch.filter((entry) => !declaredNames.includes(entry.name))
    if (unknown.length) {
        const details = unknown.map((entry) => {
            const near = closeNames(entry.name, declaredNames)
            return near.length
                ? `${entry.name} is not a variable of this notebook. Did you mean: ${near.join(', ')}?`
                : `${entry.name} is not a variable of this notebook.`
        })
        const remedy = declaredNames.length
            ? ` This notebook declares: ${[...declaredNames].sort().join(', ')}. Add a new variable with notebooks-set-variables.`
            : ' This notebook declares no variables. Declare one with notebooks-set-variables.'
        throw new Error(details.join(' ') + remedy)
    }

    const byName = new Map(patch.map((entry) => [entry.name, entry]))
    return declared.map((variable) => {
        const entry = byName.get(variable.name)
        if (!entry) {
            return variable
        }
        return { name: variable.name, type: entry.type ?? variable.type, value: entry.value }
    })
}

/**
 * Index in the plan to resume at.
 *
 * An unrecognized cursor throws rather than restarting the pass: treating a deleted or invented
 * node id as "start from the top" would re-run the whole notebook and provision a sandbox on the
 * strength of a bad string, so the expensive mistake is the loud one.
 */
export function resolveCursor(plan: PlannedCell[], resumeAfterNodeId: string | undefined): number {
    if (!resumeAfterNodeId) {
        return 0
    }
    const index = plan.findIndex((cell) => cell.node_id === resumeAfterNodeId)
    if (index === -1) {
        throw new Error(
            `resume_after_node_id ${resumeAfterNodeId} is not a runnable cell of this notebook. ` +
                `Runnable cells, in run order: ${plan.map((cell) => cell.node_id).join(', ') || '(none)'}. ` +
                'Omit resume_after_node_id to run the notebook from the first cell.'
        )
    }
    return index + 1
}
