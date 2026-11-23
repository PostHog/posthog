import api from 'lib/api'
import { apiMutator } from 'lib/api-orval-mutator'

import {
    warehouseTablesCreateFromUploadCreate,
    warehouseTablesUploadFileCreate,
} from 'products/data_warehouse/frontend/generated/api'

import { notebooksSqlV2RunsRetrieve } from './generated/api'
import { saveResultCohort, saveResultTable } from './sqlResultSnapshot'

jest.mock('./generated/api', () => ({ notebooksSqlV2RunsRetrieve: jest.fn() }))
jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesCreateFromUploadCreate: jest.fn(),
    warehouseTablesUploadFileCreate: jest.fn(),
}))
jest.mock('lib/api-orval-mutator', () => ({ apiMutator: jest.fn() }))

const source = { projectId: '2', shortId: 'notebook', nodeId: 'cell', runId: 'run' }
const run = jest.mocked(notebooksSqlV2RunsRetrieve)
const upload = jest.mocked(warehouseTablesUploadFileCreate)
const create = jest.mocked(warehouseTablesCreateFromUploadCreate)

describe('saving a notebook SQL run', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('uploads captured rows beyond the preview and links the returned table and source', async () => {
        run.mockResolvedValue({
            status: 'done',
            result: { status: 'ok', columns: ['n'], first_page: [[1]], has_more: true },
            rows: [[1], [null], [3]],
        })
        upload.mockResolvedValue({ upload_id: 'upload', filename: 'result.json', file_format: 'json', size_bytes: 24 })
        create.mockResolvedValue({ id: 'table', name: 'counts', pending_source_id: 'source' } as Awaited<
            ReturnType<typeof create>
        >)
        await expect(saveResultTable(source, { name: 'counts' })).resolves.toEqual({
            id: 'table',
            name: 'counts',
            sourceId: 'source',
        })
        const file = upload.mock.calls[0][1]!.file!
        expect(await file.text()).toBe('{"n":1}\n{"n":null}\n{"n":3}\n')
        expect(create).toHaveBeenCalledWith('2', {
            upload_id: 'upload',
            filename: 'result.json',
            file_format: 'json',
            table_name: 'counts',
            notebook_cell: 'notebook/cell',
        })
    })

    it('refuses an expired direct result or an interrupted run before uploading any rows', async () => {
        const result = {
            status: 'ok',
            columns: ['n'],
            first_page: [[1]],
            has_more: true,
            row_count: 1,
            result_id: 'display-id',
        }
        run.mockResolvedValueOnce({ status: 'done', result }).mockResolvedValueOnce({ status: 'interrupted', result })
        await expect(saveResultTable(source, { name: 'counts' })).rejects.toThrow('expired')
        await expect(saveResultTable(source, { name: 'counts' })).rejects.toThrow('successfully')
        expect(upload).not.toHaveBeenCalled()
    })

    it('leaves an existing table alone when a saved frame ends early', async () => {
        const columns = ['n']
        run.mockResolvedValue({
            status: 'done',
            result: { status: 'ok', columns, first_page: [[1]], has_more: true, row_count: 3, result_id: 'frame' },
        })
        jest.spyOn(api.notebooks, 'sqlV2RunPage').mockResolvedValue({
            columns,
            types: [],
            rows: [[1], [2]],
            has_more: false,
        })
        await expect(saveResultTable(source, { tableId: 'table' })).rejects.toThrow('unavailable')
        expect(upload).not.toHaveBeenCalled()
    })

    it('reads the saved frame through its last page and deduplicates and quotes cohort identifiers', async () => {
        const columns = ['distinct_id']
        run.mockResolvedValue({
            status: 'done',
            result: { status: 'ok', columns, first_page: [['one']], has_more: true, row_count: 3, result_id: 'frame' },
        })
        const page = jest.spyOn(api.notebooks, 'sqlV2RunPage')
        page.mockResolvedValueOnce({ columns, types: [], rows: [['one'], ['one']], has_more: true })
        page.mockResolvedValueOnce({ columns, types: [], rows: [['a,"b"']], has_more: false })
        await saveResultCohort(source, 'Readers')
        expect(page).toHaveBeenLastCalledWith('notebook', 'run', { limit: 500, offset: 2 })
        const body = jest.mocked(apiMutator).mock.calls[0][1].body as FormData
        expect(body.get('is_static')).toBe('true')
        expect(await (body.get('csv') as File).text()).toBe('distinct_id,row\r\n"one",1\r\n"a,""b""",2')
    })
})
