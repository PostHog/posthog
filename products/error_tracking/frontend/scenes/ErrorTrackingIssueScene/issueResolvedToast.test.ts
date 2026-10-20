import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { hogqlQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import type { CohortApi } from 'products/cohorts/frontend/generated/api.schemas'
import * as messageAudience from 'products/workflows/frontend/MessageAudience/messageAudience'
import * as messageAudienceWarnings from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

import { showIssueResolvedToast } from './issueResolvedToast'
import * as issueAffectedBroadcast from './ScenePanel/issueAffectedBroadcastLogic'

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

    it.each([
        { scenario: 'opens the email when the person stays on the issue', leaves: false, opened: true },
        {
            scenario: 'does not open the email when the person left while the cohort saved',
            leaves: true,
            opened: false,
        },
    ])('$scenario', async ({ leaves, opened }) => {
        initKeaTests()
        router.actions.push('/error_tracking/issue-1')
        mockHogqlQuery.mockResolvedValue({ results: [[3, 2]] } as never)
        jest.spyOn(issueAffectedBroadcast, 'createAffectedPeopleCohort').mockImplementation(async () => {
            if (leaves) {
                router.actions.push('/insights')
            }
            return { id: 7 } as CohortApi
        })
        const open = jest.spyOn(messageAudienceWarnings, 'openMessageAudience').mockResolvedValue()
        const success = jest.spyOn(lemonToast, 'success')

        await showIssueResolvedToast('1', { issueId: 'issue-1', issueName: 'Checkout timeout' })
        await success.mock.calls[0]?.[1]?.button?.action()

        expect(open).toHaveBeenCalledTimes(opened ? 1 : 0)
    })
})
