import type { NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'
import { ConcurrencyController } from 'lib/utils/concurrencyController'
import { type NotebookNodeSQLV2Result, toCachedResults } from 'scenes/notebooks/Nodes/NotebookNodeSQLV2'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { notebooksSqlV2RunsRetrieve } from '../generated/api'
import type { NotebookAppReleaseApi } from '../generated/api.schemas'
import { appSourceCells } from './notebookAppLayout'
import type { ViewerProps } from './notebookAppViewerLogic'

const SAVED_SQL_ROW_LIMIT = 300

export type SavedRows = 'complete' | 'partial' | 'capped'
export type PublishedRunResult = { result: HogQLQueryResponse; rows: SavedRows } | 'unavailable'

export function savedQueryResult(
    attributes: NotebookComponentProps,
    pinned?: PublishedRunResult
): PublishedRunResult | 'loading' | undefined {
    if (typeof attributes.runId === 'string' && attributes.runId) {
        return pinned ?? 'loading'
    }
    if (attributes.connectionId || attributes.sendRawQuery) {
        return 'unavailable'
    }
    const saved = attributes.result as NotebookNodeSQLV2Result | undefined
    if (saved) {
        const result = toCachedResults(saved)
        return { result, rows: saved.has_more || saved.row_count > result.results.length ? 'partial' : 'complete' }
    }
}

function savedRowsStatus(retained: number | undefined, hasMore?: boolean): SavedRows {
    if (retained === undefined) {
        return hasMore ? 'partial' : 'complete'
    }
    return retained >= SAVED_SQL_ROW_LIMIT ? 'capped' : 'complete'
}

async function readPublishedRun(
    viewer: ViewerProps,
    nodeId: string,
    runId: string,
    signal: AbortSignal
): Promise<PublishedRunResult> {
    const run = await notebooksSqlV2RunsRetrieve(viewer.project, viewer.shortId, runId, { node_id: nodeId }, { signal })
    const envelope = run.result
    if (!envelope || envelope.error || !['done', 'interrupted'].includes(run.status)) {
        return 'unavailable'
    }
    const rows = run.rows ?? envelope.first_page ?? []
    return {
        result: toCachedResults({
            columns: envelope.columns ?? [],
            types: envelope.types?.map(([name, type]) => [name, type]),
            first_page: rows as NotebookNodeSQLV2Result['first_page'],
            row_count: envelope.row_count ?? rows.length,
        }),
        rows: savedRowsStatus(run.rows?.length, envelope.has_more),
    }
}

export async function restorePublishedResults(
    viewer: ViewerProps,
    release: NotebookAppReleaseApi,
    controller: AbortController
): Promise<Record<string, PublishedRunResult>> {
    const displayed = new Set(
        release.layout.blocks.filter((b) => b.kind === 'cell' && b.display !== 'source').map((b) => b.node_id)
    )
    const results: Record<string, PublishedRunResult> = {}
    const requests = new ConcurrencyController(4)
    await Promise.all(
        appSourceCells(release.markdown).map(async (cell) => {
            if (
                !displayed.has(cell.id) ||
                cell.type !== 'component' ||
                cell.tagName !== 'SQLV2' ||
                typeof cell.props.runId !== 'string' ||
                !cell.props.runId
            ) {
                return
            }
            const runId = cell.props.runId
            try {
                results[cell.id] = await requests.run({
                    abortController: controller,
                    fn: () => readPublishedRun(viewer, cell.id, runId, controller.signal),
                })
            } catch (error) {
                if (controller.signal.aborted) {
                    throw error
                }
                results[cell.id] = 'unavailable'
            }
        })
    )
    return results
}
