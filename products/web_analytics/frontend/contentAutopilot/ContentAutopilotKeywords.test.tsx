import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'

import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { aeoKeywordsList, aeoKeywordsReport } from '../generated/api'
import { ContentAutopilotKeywords } from './ContentAutopilotKeywords'
import { EXAMPLE_KEYWORD_REPORT, EXAMPLE_KEYWORDS } from './contentAutopilotStoryFixtures'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    aeoKeywordsList: jest.fn(),
    aeoKeywordsReport: jest.fn(),
    aeoKeywordsModifiers: jest.fn().mockResolvedValue(null),
}))
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const SEARCH_CONSOLE_TABLE = 'googlesearchconsole.search_analytics_by_query'

describe('ContentAutopilotKeywords', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.mocked(aeoKeywordsList).mockResolvedValue(EXAMPLE_KEYWORDS)
        jest.mocked(aeoKeywordsReport).mockResolvedValue(EXAMPLE_KEYWORD_REPORT)
        jest.mocked(performQuery).mockImplementation(async (query: any) =>
            query.kind === NodeKind.DatabaseSchemaQuery
                ? {
                      tables: {
                          [SEARCH_CONSOLE_TABLE]: {
                              type: 'data_warehouse',
                              id: 'gsc',
                              name: SEARCH_CONSOLE_TABLE,
                              fields: {},
                          },
                      },
                      joins: [],
                  }
                : { results: [] }
        )
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the keyword editor in a modal that the manage button opens', async () => {
        render(<ContentAutopilotKeywords />)

        fireEvent.click(await screen.findByText('Manage keywords'))

        const list = await screen.findByTestId('content-autopilot-keywords-list')
        expect(within(list).getByText(EXAMPLE_KEYWORDS[0].keyword)).toBeTruthy()
    })

    it('groups the columns into AI answers and Google search', async () => {
        render(<ContentAutopilotKeywords />)

        const report = await screen.findByTestId('content-autopilot-keywords-report')
        const headerRows = report.querySelectorAll('thead tr')
        const groups = Array.from(headerRows[0].querySelectorAll('th')).map((cell) => cell.textContent)
        expect(groups).toEqual(['', 'AI answers', 'Google search'])
        expect(await within(report).findByText('Impressions')).toBeTruthy()
    })
})
