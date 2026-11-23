import api from 'lib/api'
import { apiMutator } from 'lib/api-orval-mutator'

import { getCohortsCreateUrl } from 'products/cohorts/frontend/generated/api'
import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'
import {
    warehouseTablesCreateFromUploadCreate,
    warehouseTablesReplaceFileCreate,
    warehouseTablesUploadFileCreate,
} from 'products/data_warehouse/frontend/generated/api'
import { getCohortIdentifier } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import { notebooksSqlV2RunsRetrieve } from './generated/api'

export type SqlResultSource = { projectId: string; shortId: string; nodeId: string; runId: string }
export type SavedSqlResultTable = { id: string; name: string; sourceId: string | null }

const MAX_FILE_BYTES = 50 * 1024 * 1024
const PAGE_SIZE = 500

async function* resultPages({ projectId, shortId, runId }: SqlResultSource): AsyncGenerator<{
    columns: string[]
    rows: unknown[][]
}> {
    const { status, result, rows } = await notebooksSqlV2RunsRetrieve(projectId, shortId, runId)
    if (status !== 'done' || !result?.columns?.length || result.error) {
        throw new Error('Run the SQL cell successfully before saving its results.')
    }
    const columns = result.columns
    if (rows) {
        yield { columns, rows }
        return
    }
    const firstPage = result.first_page ?? []
    if (!result.has_more && (result.row_count ?? firstPage.length) <= firstPage.length) {
        yield { columns, rows: firstPage }
        return
    }
    const rowCount = result.row_count ?? 0
    if (!result.result_id || rowCount <= firstPage.length) {
        throw new Error('The full result has expired. Run the cell again before saving it.')
    }

    let offset = 0
    while (offset < rowCount) {
        const page = await api.notebooks.sqlV2RunPage(shortId, runId, { offset, limit: PAGE_SIZE })
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

export async function saveResultTable(
    source: SqlResultSource,
    destination: { name: string } | { tableId: string }
): Promise<SavedSqlResultTable> {
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
    const upload = await warehouseTablesUploadFileCreate(source.projectId, {
        file: new File(chunks, 'notebook-result.json', { type: 'application/x-ndjson' }),
        file_format: 'json',
    })
    const file = {
        upload_id: upload.upload_id,
        filename: upload.filename,
        file_format: 'json' as const,
        notebook_cell: `${source.shortId}/${source.nodeId}`,
    }
    const table =
        'tableId' in destination
            ? await warehouseTablesReplaceFileCreate(source.projectId, destination.tableId, file)
            : await warehouseTablesCreateFromUploadCreate(source.projectId, { ...file, table_name: destination.name })
    return {
        id: table.id,
        name: table.name,
        sourceId: table.pending_source_id ?? table.external_data_source?.id ?? null,
    }
}

export async function saveResultCohort(source: SqlResultSource, name: string): Promise<CohortApi> {
    const identifiers = new Set<string>()
    const chunks: Blob[] = []
    let size = 0
    let header = ''
    for await (const { columns, rows } of resultPages(source)) {
        const identifier = getCohortIdentifier(columns)
        if (!identifier) {
            throw new Error('Return a person_id, actor_id, or distinct_id column to save a cohort.')
        }
        header = identifier === 'distinct_id' ? 'distinct_id' : 'person_id'
        const column = columns.indexOf(identifier)
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
        const chunk = new Blob(lines)
        size += chunk.size
        if (size > MAX_FILE_BYTES) {
            throw new Error('The list of people exceeds 50 MiB. Narrow the query and run it again.')
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
    body.set('csv', new File([header + ',row', ...chunks], 'notebook-cohort.csv', { type: 'text/csv' }))
    return apiMutator<CohortApi>(getCohortsCreateUrl(source.projectId), { method: 'POST', body })
}
