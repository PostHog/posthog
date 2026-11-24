import { apiMutator } from 'lib/api-orval-mutator'

import { getCohortsCreateUrl } from 'products/cohorts/frontend/generated/api'
import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'
import {
    warehouseTablesCreateFromFileCreate,
    warehouseTablesReplaceWithFileCreate,
    warehouseTablesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { TableApi } from 'products/data_warehouse/frontend/generated/api.schemas'
import { getCohortIdentifier } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import { notebooksSqlV2RunsPageRetrieve, notebooksSqlV2RunsRetrieve } from './generated/api'
import type { NotebookSQLV2EnvelopeApi } from './generated/api.schemas'

export type SqlResultSource = { projectId: string; shortId: string; nodeId: string; runId: string }
export type SavedSqlResultTable = { id: string; name: string; sourceId: string | null }

const MAX_FILE_BYTES = 50 * 1024 * 1024
const PAGE_SIZE = 500
const MAX_FRAME_ROWS = 10_000

type ResultPage = { columns: string[]; rows: unknown[][] }

export async function getTableForUpdate(projectId: string, link: SavedSqlResultTable): Promise<TableApi> {
    const table = await warehouseTablesRetrieve(projectId, link.id, { include_columns: false })
    const sourceId = table.pending_source_id ?? table.external_data_source?.id
    if (table.name !== link.name || (link.sourceId && link.sourceId !== sourceId)) {
        throw new Error('The warehouse table no longer matches this link. Remove the link and save under a new name.')
    }
    return table
}

async function* resultPages(source: SqlResultSource): AsyncGenerator<ResultPage> {
    const { status, result, rows } = await notebooksSqlV2RunsRetrieve(source.projectId, source.shortId, source.runId, {
        node_id: source.nodeId,
    })
    if (status !== 'done' || !result?.columns?.length || result.error) {
        throw new Error('Run the SQL cell successfully before saving its results.')
    }
    const columns = result.columns
    if (rows) {
        yield { columns, rows }
        return
    }
    if (result.delivery === 'direct') {
        yield { columns, rows: completeDirectRows(result) }
        return
    }
    if (!result.result_id || result.row_count == null) {
        throw new Error('The full result has expired. Run the cell again before saving it.')
    }
    yield* storedFramePages(source, columns, result.row_count)
}

function completeDirectRows(result: NotebookSQLV2EnvelopeApi): unknown[][] {
    if (!result.first_page || result.has_more || result.first_page.length !== result.row_count) {
        throw new Error('The full result has expired. Run the cell again before saving it.')
    }
    return result.first_page
}

async function* storedFramePages(
    { projectId, shortId, runId }: SqlResultSource,
    columns: string[],
    rowCount: number
): AsyncGenerator<ResultPage> {
    if (rowCount > MAX_FRAME_ROWS) {
        throw new Error('Save up to 10,000 rows at a time. Narrow the query and run it again.')
    }

    let offset = 0
    while (offset < rowCount) {
        const page = await notebooksSqlV2RunsPageRetrieve(projectId, shortId, runId, { offset, limit: PAGE_SIZE })
        if (page.columns.length !== columns.length || page.columns.some((name, index) => name !== columns[index])) {
            throw new Error('The result columns changed. Run the cell again before saving it.')
        }
        offset += page.rows.length
        if (!page.rows.length || offset > rowCount || page.has_more !== offset < rowCount) {
            throw new Error('The full result is unavailable. Run the cell again before saving it.')
        }
        yield { columns, rows: page.rows }
    }
}

async function resultTableFile(source: SqlResultSource): Promise<File> {
    const chunks: Blob[] = []
    let size = 0
    for await (const { columns, rows } of resultPages(source)) {
        if (new Set(columns).size !== columns.length || columns.some((column) => !column.trim())) {
            throw new Error('Give each result column a unique name before saving a table.')
        }
        const lines = rows.map((row) => {
            if (row.length !== columns.length) {
                throw new Error('The result contains a row with missing columns.')
            }
            const record = Object.fromEntries(columns.map((column, index) => [column, row[index]]))
            return JSON.stringify(record) + '\n'
        })
        const chunk = new Blob(lines)
        size += chunk.size
        if (size > MAX_FILE_BYTES) {
            throw new Error('The result exceeds the 50 MiB upload limit. Narrow the query and run it again.')
        }
        chunks.push(chunk)
    }
    if (!size) {
        throw new Error('The query returned no rows to save.')
    }
    return new File(chunks, 'notebook-result.json', { type: 'application/x-ndjson' })
}

export type PendingTableUpload = { file?: File }

export async function saveResultTable(
    source: SqlResultSource,
    destination: { name: string } | { tableId: string },
    pending: PendingTableUpload
): Promise<SavedSqlResultTable> {
    const upload = {
        file: (pending.file ??= await resultTableFile(source)),
        file_format: 'json' as const,
        notebook_cell: `${source.shortId}/${source.nodeId}`,
    }
    const table =
        'tableId' in destination
            ? await warehouseTablesReplaceWithFileCreate(source.projectId, destination.tableId, upload)
            : await warehouseTablesCreateFromFileCreate(source.projectId, { ...upload, table_name: destination.name })
    return {
        id: table.id,
        name: table.name,
        sourceId: table.pending_source_id ?? table.external_data_source?.id ?? null,
    }
}

function cohortCsvPage(rows: unknown[][], column: number, identifiers: Set<string>): Blob {
    const lines: string[] = []
    for (const row of rows) {
        const id = row[column]
        if (typeof id !== 'string' && typeof id !== 'number') {
            continue
        }
        const value = String(id)
        if (!value || identifiers.has(value)) {
            continue
        }
        if (value.trim() !== value) {
            throw new Error(
                'The cohort importer trims surrounding whitespace. Return identifiers without surrounding whitespace.'
            )
        }
        identifiers.add(value)
        lines.push(`\r\n"${value.replaceAll('"', '""')}",${identifiers.size}`)
    }
    return new Blob(lines)
}

export async function saveResultCohort(source: SqlResultSource, name: string, maxBytes: number): Promise<CohortApi> {
    const identifiers = new Set<string>()
    const chunks: Blob[] = []
    let size = 0
    let header = ''
    for await (const { columns, rows } of resultPages(source)) {
        const identifier = getCohortIdentifier(columns)
        if (!identifier) {
            throw new Error('Return a person_id, actor_id, or distinct_id column to save a cohort.')
        }
        header = identifier === 'distinct_id' ? 'distinct_id,row' : 'person_id,row'
        const chunk = cohortCsvPage(rows, columns.indexOf(identifier), identifiers)
        size += chunk.size
        if (header.length + size > maxBytes) {
            throw new Error('The list of people exceeds the cohort upload limit. Narrow the query and run it again.')
        }
        chunks.push(chunk)
    }
    if (!identifiers.size) {
        throw new Error('The result contains no person identifiers.')
    }
    const body = new FormData()
    body.set('name', name)
    body.set('is_static', 'true')
    // A one-column CSV treats "distinct_id" as a member. A second named column selects header-based import.
    body.set('csv', new File([header, ...chunks], 'notebook-cohort.csv', { type: 'text/csv' }))
    return apiMutator<CohortApi>(getCohortsCreateUrl(source.projectId), { method: 'POST', body })
}
