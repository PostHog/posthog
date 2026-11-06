import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_LOGS_COLUMNS, LogsColumnConfig } from '../LogsViewer/config/columns'
import { logsViewerConfigLogic } from '../LogsViewer/config/logsViewerConfigLogic'
import { logsViewsListLogic } from './logsViewsListLogic'
import { LogsView } from './logsViewsLogic'

const TEST_ID = 'test-views'

const CUSTOM_COLUMNS: LogsColumnConfig[] = [
    { id: 'timestamp', type: 'timestamp', width: 180 },
    { id: 'level', type: 'level' },
    { id: 'col-1', type: 'custom', expression: 'attributes.http.method', name: 'Method' },
    { id: 'message', type: 'message' },
]

const makeView = (overrides: Partial<LogsView> = {}): LogsView =>
    ({
        id: 'view-uuid',
        short_id: 'abc123',
        name: 'My view',
        filters: { searchTerm: 'boom' },
        columns: null,
        pinned: false,
        created_at: '2026-10-20T00:00:00Z',
        created_by: {} as LogsView['created_by'],
        updated_at: null,
        ...overrides,
    }) as LogsView

describe('logsViewsListLogic', () => {
    let logic: ReturnType<typeof logsViewsListLogic.build>
    let configLogic: ReturnType<typeof logsViewerConfigLogic.build>
    let createdPayload: Record<string, any> | null

    beforeEach(() => {
        createdPayload = null
        useMocks({
            get: {
                '/api/projects/:team_id/logs/views/': () => [200, { results: [] }],
            },
            post: {
                '/api/projects/:team_id/logs/views/': async ({ request }) => {
                    createdPayload = (await request.json()) as Record<string, any>
                    return [200, makeView({ ...createdPayload })]
                },
                '/api/environments/:team_id/logs/query/': () => [200, { results: [], maxExportableLogs: 5000 }],
                '/api/environments/:team_id/logs/sparkline/': () => [200, []],
            },
        })
        initKeaTests()
        configLogic = logsViewerConfigLogic({ id: TEST_ID })
        configLogic.mount()
        logic = logsViewsListLogic({ id: TEST_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        configLogic.unmount()
    })

    it.each([
        ['as is when the API accepts every column', CUSTOM_COLUMNS, CUSTOM_COLUMNS],
        [
            'with integer widths and no blank names',
            [
                { id: 'timestamp', type: 'timestamp', width: 180.6 },
                { id: 'col-1', type: 'custom', expression: 'attributes.http.method', name: '   ' },
                { id: 'col-2', type: 'custom', expression: 'attributes.region', name: ' Region ', width: 5000 },
                { id: 'message', type: 'message' },
            ],
            [
                { id: 'timestamp', type: 'timestamp', width: 181 },
                { id: 'col-1', type: 'custom', expression: 'attributes.http.method' },
                { id: 'col-2', type: 'custom', expression: 'attributes.region', name: 'Region', width: 2000 },
                { id: 'message', type: 'message' },
            ],
        ],
    ] as [string, LogsColumnConfig[], LogsColumnConfig[]][])(
        'saving a view sends the current columns %s',
        async (_, currentColumns, expectedColumns) => {
            configLogic.actions.setColumns(currentColumns)

            await expectLogic(logic, () => {
                logic.actions.setViewName('With columns')
                logic.actions.saveView()
            }).toDispatchActions(['createView', 'createViewSuccess'])

            expect(createdPayload?.name).toEqual('With columns')
            expect(createdPayload?.columns).toEqual(expectedColumns)
        }
    )

    it.each([
        ['restores the saved columns', CUSTOM_COLUMNS, CUSTOM_COLUMNS],
        ['falls back to the default columns when the view has no column preference', null, DEFAULT_LOGS_COLUMNS],
    ])('loading a view %s', async (_, savedColumns, expectedColumns) => {
        configLogic.actions.setColumns([{ id: 'level', type: 'level' }])

        await expectLogic(logic, () => {
            logic.actions.loadView(makeView({ columns: savedColumns }))
        }).toFinishAllListeners()

        expect(configLogic.values.columns).toEqual(expectedColumns)
    })
})
