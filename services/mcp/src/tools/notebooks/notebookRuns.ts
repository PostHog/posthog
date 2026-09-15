import type { Schemas } from '@/api/generated'
import type { Context } from '@/tools/types'

import {
    buildResultProp,
    POLL_DELAYS_MS,
    RUN_WAIT_BUDGET_MS,
    shapeRunForModel,
    sleep,
    type ShapedRunResult,
} from './cellRuns'
import { findCellTag, readStringProp, replaceCellTag, upsertProp } from './cellTags'
import { applyMarkdownEdit } from './markdownDoc'

export interface NotebookRunCellOutcome {
    node_id: string
    dataframe_name?: string
    /** 'running', 'done', 'failed', 'interrupted', or null before the run reaches the cell. */
    status: string | null
    run?: ShapedRunResult
}

export interface NotebookRunOutcome {
    run_id: string
    status: string
    cell_count: number
    completed_count: number
    failed_cell?: string
    cells: NotebookRunCellOutcome[]
    starts_sandbox?: boolean
    sandbox_hourly_price?: number | null
    hint?: string
}

const STILL_RUNNING_HINT =
    'The notebook is still running. Call notebooks-run-status with this run_id to keep waiting and to write the remaining results into the document.'

const TERMINAL_CELL_STATUSES = new Set(['done', 'failed', 'interrupted'])

/**
 * How many cells one document save may carry. Batching keeps a poll that finds a whole
 * notebook's worth of finished cells — the agent that started a run and came back later —
 * from holding every result envelope in memory at once, since a single envelope can run to
 * megabytes. A normal poll finds far fewer than this, so it still saves once.
 */
const MAX_CELLS_PER_SAVE = 10

/** A cell result already written into the document, keyed by the run that produced it. */
function alreadyWritten(markdown: string, nodeId: string, runId: string): boolean {
    const block = findCellTag(markdown, nodeId)
    return !!block && readStringProp(block.source, 'runId') === runId
}

/**
 * Wait for a whole-notebook run, writing each cell's result into the document as it lands.
 *
 * One `applyMarkdownEdit` per poll, not per cell: a ten-cell run would otherwise save the
 * document ten times in a few seconds, and every save is a version bump other editors see.
 * Returns as soon as the run is terminal, or when the budget runs out — in which case the
 * caller tells the agent to continue with notebooks-run-status.
 */
export async function awaitNotebookRun(
    context: Context,
    notebookId: string,
    notebookPath: string,
    runId: string,
    waitBudgetMs: number = RUN_WAIT_BUDGET_MS
): Promise<NotebookRunOutcome> {
    const deadline = Date.now() + waitBudgetMs
    const shapedByNodeId = new Map<string, ShapedRunResult>()
    const writtenRunIds = new Set<string>()
    let pollIndex = 0

    for (;;) {
        const status = await context.api.request<Schemas.NotebookRunStatusResponse>({
            method: 'GET',
            path: `${notebookPath}runs/${encodeURIComponent(runId)}/`,
        })
        await writeLandedCells(context, notebookId, notebookPath, status, shapedByNodeId, writtenRunIds)

        if (status.status !== 'running') {
            return buildOutcome(runId, status, shapedByNodeId)
        }
        const delay = POLL_DELAYS_MS[Math.min(pollIndex, POLL_DELAYS_MS.length - 1)]!
        pollIndex += 1
        if (Date.now() + delay > deadline) {
            return { ...buildOutcome(runId, status, shapedByNodeId), hint: STILL_RUNNING_HINT }
        }
        await sleep(delay)
    }
}

async function writeLandedCells(
    context: Context,
    notebookId: string,
    notebookPath: string,
    status: Schemas.NotebookRunStatusResponse,
    shapedByNodeId: Map<string, ShapedRunResult>,
    writtenRunIds: Set<string>
): Promise<void> {
    const landed = status.cells.filter(
        (cell) => cell.run_id && !writtenRunIds.has(cell.run_id) && TERMINAL_CELL_STATUSES.has(cell.status ?? '')
    )
    for (let start = 0; start < landed.length; start += MAX_CELLS_PER_SAVE) {
        await writeCellBatch(
            context,
            notebookId,
            notebookPath,
            landed.slice(start, start + MAX_CELLS_PER_SAVE),
            shapedByNodeId,
            writtenRunIds
        )
    }
}

async function writeCellBatch(
    context: Context,
    notebookId: string,
    notebookPath: string,
    batch: Schemas.NotebookRunCell[],
    shapedByNodeId: Map<string, ShapedRunResult>,
    writtenRunIds: Set<string>
): Promise<void> {
    const envelopes: { nodeId: string; runId: string; envelope: Schemas.NotebookSQLV2Envelope | null }[] = []
    for (const cell of batch) {
        const cellRunId = cell.run_id!
        writtenRunIds.add(cellRunId)
        const result = await context.api.request<Schemas.NotebookSQLV2RunStatusResponse>({
            method: 'GET',
            path: `${notebookPath}sql_v2/runs/${encodeURIComponent(cellRunId)}/`,
        })
        const envelope = result.result ?? null
        shapedByNodeId.set(
            cell.node_id,
            shapeRunForModel({
                run_id: cellRunId,
                status: (cell.status ?? 'failed') as ShapedRunResult['status'],
                envelope,
                error: result.error ?? null,
            })
        )
        envelopes.push({ nodeId: cell.node_id, runId: cellRunId, envelope })
    }

    await applyMarkdownEdit(context, notebookId, (current) => {
        let markdown = current
        for (const { nodeId, runId: cellRunId, envelope } of envelopes) {
            // A cell deleted while the run worked has nowhere for its result to land, and a
            // cell already carrying this run's result must not be written twice.
            if (alreadyWritten(markdown, nodeId, cellRunId)) {
                continue
            }
            const block = findCellTag(markdown, nodeId)
            if (!block) {
                continue
            }
            let source = upsertProp(block.source, 'runId', cellRunId)
            if (envelope) {
                source = upsertProp(source, 'result', buildResultProp(envelope))
            }
            markdown = replaceCellTag(markdown, block, source)
        }
        return markdown
    })
}

function buildOutcome(
    runId: string,
    status: Schemas.NotebookRunStatusResponse,
    shapedByNodeId: Map<string, ShapedRunResult>
): NotebookRunOutcome {
    const cells: NotebookRunCellOutcome[] = status.cells.map((cell) => ({
        node_id: cell.node_id,
        ...(cell.dataframe_name ? { dataframe_name: cell.dataframe_name } : {}),
        status: cell.status ?? null,
        ...(shapedByNodeId.has(cell.node_id) ? { run: shapedByNodeId.get(cell.node_id)! } : {}),
    }))
    return {
        run_id: runId,
        status: status.status,
        cell_count: status.cell_count,
        completed_count: cells.filter((cell) => cell.status === 'done').length,
        ...(status.failed_node_id ? { failed_cell: status.failed_node_id } : {}),
        cells,
    }
}
