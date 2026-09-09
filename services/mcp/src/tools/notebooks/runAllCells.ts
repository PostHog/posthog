import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import {
    awaitRun,
    dispatchRun,
    RUN_WAIT_BUDGET_MS,
    shapeRunForModel,
    wrapRunResultAsInformational,
    writeRunBack,
    type ShapedRunResult,
} from './cellRuns'
import { collectRunRefs, DATAFRAME_NAME_REGEX, parseCellTags } from './cellTags'
import { notebookPathFor } from './markdownDoc'
import { NOTEBOOK_SHORT_ID_DESCRIPTION, notebookIdAliases } from './notebookId'
import { applyVariablePatch, buildRunPlan, MAX_NOTEBOOK_VARIABLES, resolveCursor, type PlannedCell } from './runPlan'

/**
 * Reserve enough of the pass budget for one dispatch plus its write-back. Starting a cell we
 * cannot wait on at all would spend a run slot and still return `running`, so the pass stops
 * one cell earlier instead and lets the next call start that cell cleanly.
 */
const MIN_CELL_BUDGET_MS = 5_000

const RunAllCellsInputSchema = z
    .object({
        notebook_id: z.string().describe(NOTEBOOK_SHORT_ID_DESCRIPTION),
        variables: z
            .array(
                z
                    .object({
                        name: z
                            .string()
                            .regex(DATAFRAME_NAME_REGEX)
                            .describe(
                                'Name of a variable the notebook already declares. To add, remove, or rename one, use notebooks-set-variables first.'
                            ),
                        value: z
                            .union([z.string(), z.number(), z.boolean(), z.null()])
                            .describe('The new value. Pass null to clear it.'),
                        type: z
                            .enum(['string', 'number', 'boolean', 'date'])
                            .optional()
                            .describe(
                                "Only to change the declared type; omit to keep it. A 'date' must be an absolute ISO 8601 date or datetime ('2025-01-31', '2025-01-31T09:00:00Z'); relative expressions like '-7d' are rejected, so compute the date first."
                            ),
                    })
                    .strict()
            )
            .max(MAX_NOTEBOOK_VARIABLES)
            .optional()
            .describe(
                'Variable values to change before the run — only the ones you are changing; every other variable keeps its value. Not accepted together with resume_after_node_id, because the cells already run bound the old values.'
            ),
        resume_after_node_id: z
            .string()
            .optional()
            .describe(
                "Continue an unfinished pass. Copy the response's resume.resume_after_node_id verbatim; never invent one. Omit to start a fresh pass from the first cell."
            ),
    })
    .strict()

export const NotebooksRunAllCellsSchema = z.preprocess(notebookIdAliases('notebook_id'), RunAllCellsInputSchema)

type CellStatus = 'done' | 'failed' | 'interrupted' | 'running' | 'not_run'

export interface RunAllCellsResult {
    status: 'done' | 'running' | 'failed' | 'interrupted'
    notebook_id: string
    variables?: Schemas.NotebookVariable[]
    cells: { node_id: string; dataframe_name?: string; status: CellStatus; run_id?: string; row_count?: number }[]
    last_run?: ShapedRunResult
    failure?: {
        node_id: string
        dataframe_name?: string
        run: ShapedRunResult
        dependent_node_ids: string[]
    }
    resume?: { resume_after_node_id: string | null; remaining_cells: number }
    cycle_node_ids?: string[]
    skipped_before_cursor?: string[]
    sandbox?: { started: true; hourly_price: number | null }
    hint: string
}

function cellEntry(
    cell: PlannedCell,
    status: CellStatus,
    extra: { run_id?: string; row_count?: number } = {}
): RunAllCellsResult['cells'][number] {
    return {
        node_id: cell.node_id,
        ...(cell.dataframe_name ? { dataframe_name: cell.dataframe_name } : {}),
        status,
        ...extra,
    }
}

function isRetryableDispatchRefusal(error: unknown): boolean {
    const status = (error as { status?: number }).status
    // 409: another run holds this notebook's slot. 429: the team is at capacity. Both clear on
    // their own, so neither is a failed pass.
    return status === 409 || status === 429
}

export const runAllCellsHandler: ToolBase<typeof NotebooksRunAllCellsSchema, RunAllCellsResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksRunAllCellsSchema>
) => {
    if (params.variables?.length && params.resume_after_node_id) {
        throw new Error(
            'Pass variables only when starting a pass. Cells already run in this pass bound the old values, so changing them mid-pass would leave the notebook mixing two sets. Finish the pass, then start a new one with the new values.'
        )
    }

    const projectId = await context.stateManager.getProjectId()
    const notebookPath = notebookPathFor(projectId, params.notebook_id)
    const state = await context.api.request<Schemas.NotebookSQLV2StateResponse>({
        method: 'GET',
        path: `${notebookPath}sql_v2/state/`,
    })
    if (state.markdown === null) {
        throw new Error(
            `Notebook ${params.notebook_id} is a legacy rich-text notebook, which has no runnable cells. Only markdown notebooks run — create one with notebooks-create-markdown.`
        )
    }

    const markdownCells = parseCellTags(state.markdown)
    const { plan, cycleNodeIds } = buildRunPlan(state.cells, markdownCells)
    if (!plan.length) {
        return wrapRunResultAsInformational({
            status: 'done' as const,
            notebook_id: params.notebook_id,
            cells: [],
            hint: 'This notebook has no SQL or Python cells to run. Add one with notebooks-add-cell.',
        })
    }

    let variables = state.variables
    if (params.variables?.length) {
        const merged = applyVariablePatch(state.variables, params.variables)
        // The same PATCH notebooks-set-variables makes, so a value the server rejects — a
        // relative date, an over-long value — fails identically from either tool.
        const saved = await context.api.request<Schemas.Notebook>({
            method: 'PATCH',
            path: notebookPath,
            body: { variables: merged },
        })
        variables = saved.variables ?? merged
    }

    const startIndex = resolveCursor(plan, params.resume_after_node_id)
    const stateByNode = new Map(state.cells.map((cell) => [cell.node_id, cell]))
    const dependentsByNode = new Map(state.cells.map((cell) => [cell.node_id, cell.dependents]))

    // Cells behind the cursor ran in an earlier call, so report their state rather than this
    // pass's. A cell the document grew behind the cursor since then never ran at all, and
    // running it now would undo the ordering the cursor stands for — so name it instead.
    const behindCursor = plan.slice(0, startIndex)
    const skippedBeforeCursor = behindCursor
        .filter((cell) => stateByNode.get(cell.node_id)?.status === 'never_run')
        .map((cell) => cell.node_id)

    const result: RunAllCellsResult = {
        status: 'done',
        notebook_id: params.notebook_id,
        cells: behindCursor.map((cell) =>
            cellEntry(cell, stateByNode.get(cell.node_id)?.status === 'never_run' ? 'not_run' : 'done')
        ),
        hint: '',
        ...(params.variables?.length ? { variables } : {}),
        ...(cycleNodeIds.length ? { cycle_node_ids: cycleNodeIds } : {}),
        ...(skippedBeforeCursor.length ? { skipped_before_cursor: skippedBeforeCursor } : {}),
    }

    const passDeadline = Date.now() + RUN_WAIT_BUDGET_MS
    let lastDone: string | null = params.resume_after_node_id ?? null
    let lastOutcome: Awaited<ReturnType<typeof awaitRun>> | null = null
    let stoppedAt = startIndex

    for (let index = startIndex; index < plan.length; index++) {
        const cell = plan[index]!
        stoppedAt = index
        if (passDeadline - Date.now() < MIN_CELL_BUDGET_MS) {
            result.status = 'running'
            break
        }

        let runId: string
        const live = stateByNode.get(cell.node_id)
        if (live?.status === 'running' && live.last_run?.run_id) {
            // A run already holds this notebook's slot, so dispatching would 409. Adopting it is
            // right even when someone else started it from the editor: it is the fresh run, and
            // its result lands on the same cell.
            runId = live.last_run.run_id
        } else {
            try {
                const dispatched = await dispatchRun(context, notebookPath, {
                    node_id: cell.node_id,
                    node_type: cell.node_type,
                    code: cell.code,
                    output_name: cell.output_name,
                    refs: collectRunRefs(markdownCells, cell.node_id),
                    variables,
                })
                runId = dispatched.run_id
                if (dispatched.starts_sandbox && !result.sandbox) {
                    result.sandbox = { started: true, hourly_price: dispatched.sandbox_hourly_price ?? null }
                }
            } catch (error) {
                if (!isRetryableDispatchRefusal(error)) {
                    throw error
                }
                result.status = 'running'
                break
            }
        }

        const outcome = await awaitRun(context, notebookPath, runId, Math.max(passDeadline - Date.now(), 0))
        await writeRunBack(context, params.notebook_id, cell.node_id, runId, outcome)
        lastOutcome = outcome

        if (outcome.status === 'running') {
            result.cells.push(cellEntry(cell, 'running', { run_id: runId }))
            result.status = 'running'
            stoppedAt = index + 1
            break
        }

        if (outcome.status !== 'done') {
            result.cells.push(cellEntry(cell, outcome.status, { run_id: runId }))
            result.status = outcome.status
            result.failure = {
                node_id: cell.node_id,
                ...(cell.dataframe_name ? { dataframe_name: cell.dataframe_name } : {}),
                run: shapeRunForModel(outcome),
                dependent_node_ids: dependentsByNode.get(cell.node_id) ?? [],
            }
            stoppedAt = index + 1
            break
        }

        result.cells.push(
            cellEntry(cell, 'done', {
                run_id: runId,
                ...(outcome.envelope?.row_count !== undefined && outcome.envelope?.row_count !== null
                    ? { row_count: outcome.envelope.row_count }
                    : {}),
            })
        )
        lastDone = cell.node_id
        stoppedAt = index + 1
    }

    for (const cell of plan.slice(stoppedAt)) {
        result.cells.push(cellEntry(cell, 'not_run'))
    }

    if (result.status === 'done') {
        if (lastOutcome) {
            result.last_run = shapeRunForModel(lastOutcome)
        }
        result.hint = buildDoneHint(result)
    } else {
        // Whatever has not reached `done` still needs a run, whether it is the cell that failed,
        // the one still in flight, or the untouched tail. Counting the shortfall keeps this
        // right at every exit instead of an offset per break.
        const done = result.cells.filter((cell) => cell.status === 'done').length
        result.resume = { resume_after_node_id: lastDone, remaining_cells: plan.length - done }
        result.hint = buildUnfinishedHint(result)
    }

    return wrapRunResultAsInformational(result)
}

function cycleNote(result: RunAllCellsResult): string {
    if (!result.cycle_node_ids?.length) {
        return ''
    }
    return ` These cells form a dependency cycle and ran in document order, so at least one read a dataframe from the previous pass: ${result.cycle_node_ids.join(', ')}.`
}

function sandboxNote(result: RunAllCellsResult): string {
    if (!result.sandbox) {
        return ''
    }
    const price = result.sandbox.hourly_price
    return price === null
        ? ` This pass started the notebook's sandbox.`
        : ` This pass started the notebook's sandbox, billed at $${price} per hour — tell the user.`
}

function buildDoneHint(result: RunAllCellsResult): string {
    const ran = result.cells.filter((cell) => cell.status === 'done').length
    return (
        `Every cell ran. ${ran} ${ran === 1 ? 'cell is' : 'cells are'} up to date against the notebook's current variables. ` +
        `To read any cell's rows beyond the last one, call notebooks-run-cell-result with that cell's run_id.` +
        cycleNote(result) +
        sandboxNote(result)
    )
}

function buildUnfinishedHint(result: RunAllCellsResult): string {
    const cursor = result.resume?.resume_after_node_id
    const again = `Call notebooks-run-all-cells again with resume_after_node_id ${cursor === null ? 'omitted' : `"${cursor}"`} to continue.`

    if (result.status === 'running') {
        return (
            `The pass is unfinished: ${result.resume?.remaining_cells ?? 0} cell(s) still to run. ${again}` +
            cycleNote(result) +
            sandboxNote(result)
        )
    }

    const dependents = result.failure?.dependent_node_ids ?? []
    const downstream = dependents.length
        ? ` ${dependents.length} cell(s) read this cell's dataframe and were not run: ${dependents.join(', ')}.`
        : ` No cell reads this cell's dataframe.`
    return (
        `The pass stopped at cell ${result.failure?.node_id} (${result.status}) and did not continue, because downstream cells would have run against the previous pass's dataframe and looked fresh.${downstream}` +
        ` Fix it with notebooks-update-cell, then ${again.charAt(0).toLowerCase()}${again.slice(1)}` +
        cycleNote(result) +
        sandboxNote(result)
    )
}

const tool = (): ToolBase<typeof NotebooksRunAllCellsSchema, RunAllCellsResult> => ({
    name: 'notebooks-run-all-cells',
    schema: NotebooksRunAllCellsSchema,
    handler: runAllCellsHandler,
})

export default tool
