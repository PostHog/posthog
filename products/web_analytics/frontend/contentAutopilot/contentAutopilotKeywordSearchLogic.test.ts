import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { aeoKeywordsReport } from '../generated/api'
import { contentAutopilotKeywordSearchLogic } from './contentAutopilotKeywordSearchLogic'
import { EXAMPLE_KEYWORD_REPORT } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    aeoKeywordsList: jest.fn().mockResolvedValue([]),
    aeoKeywordsReport: jest.fn(),
    aeoKeywordsModifiers: jest.fn().mockResolvedValue(null),
}))
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const warehouseTable = (name: string): Record<string, unknown> => ({
    type: 'data_warehouse',
    id: name,
    name,
    fields: {},
})

describe('contentAutopilotKeywordSearchLogic', () => {
    let logic: ReturnType<typeof contentAutopilotKeywordSearchLogic.build>
    let impressionQueries: string[]

    const mockQueries = (tableNames: string[]): void => {
        jest.mocked(performQuery).mockImplementation(async (query: any) => {
            if (query.kind === NodeKind.DatabaseSchemaQuery) {
                return { tables: Object.fromEntries(tableNames.map((name) => [name, warehouseTable(name)])), joins: [] }
            }
            impressionQueries.push(query.query)
            return { results: [['feature flags', 26292, 514, 561, 9.8]] }
        })
    }

    beforeEach(() => {
        jest.clearAllMocks()
        impressionQueries = []
        initKeaTests()
        jest.mocked(aeoKeywordsReport).mockResolvedValue(EXAMPLE_KEYWORD_REPORT)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('reads impressions for the report keywords over the report window', async () => {
        mockQueries(['googlesearchconsole.search_analytics_by_query'])
        logic = contentAutopilotKeywordSearchLogic()
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                searchConsoleMissing: false,
                impressionsFailed: false,
                impressions: { 'feature flags': { impressions: 26292, clicks: 514, searches: 561, position: 9.8 } },
            })
        const query = impressionQueries[impressionQueries.length - 1]
        expect(query).toContain(`toDate('${EXAMPLE_KEYWORD_REPORT.window_from}')`)
        expect(query).toContain(`toDate('${EXAMPLE_KEYWORD_REPORT.window_to}')`)
        expect(query).toContain(`'${EXAMPLE_KEYWORD_REPORT.keywords[0].keyword}'`)
    })

    it('asks for nothing and says the source is missing when the project has no Search Console table', async () => {
        mockQueries(['stripe.charges'])
        logic = contentAutopilotKeywordSearchLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ searchConsoleMissing: true, impressions: null })
        expect(impressionQueries).toEqual([])
    })
})
