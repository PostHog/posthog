import { lemonToast } from '@posthog/lemon-ui'

import { hogqlQuery } from '~/queries/query'

import * as messageAudience from 'products/workflows/frontend/MessageAudience/messageAudience'

import { showIssueResolvedToast } from './issueResolvedToast'

jest.mock('~/queries/query', () => ({ hogqlQuery: jest.fn() }))

const mockHogqlQuery = jest.mocked(hogqlQuery)

describe('showIssueResolvedToast', () => {
    beforeEach(() => {
        jest.spyOn(messageAudience, 'messageAudienceAccessDisabledReason').mockReturnValue(null)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { scenario: 'people with an email were hit', count: Promise.resolve([3, 2]), offered: true },
        { scenario: 'no one hit has an email', count: Promise.resolve([3, 0]), offered: false },
        { scenario: 'the count fails', count: Promise.reject(new Error('timeout')), offered: false },
    ])('offers the fixed email only when $scenario', async ({ count, offered }) => {
        mockHogqlQuery.mockImplementation(async () => ({ results: [await count] }) as never)
        const success = jest.spyOn(lemonToast, 'success')

        await showIssueResolvedToast('1', { issueId: 'issue-1', issueName: 'Checkout timeout' })

        expect(success.mock.calls[0]?.[1]?.button?.label).toBe(offered ? "Tell them it's fixed" : undefined)
    })
})
