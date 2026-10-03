import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { RecipientApi, RecipientPageApi } from 'products/messaging/frontend/generated/api.schemas'

import { AudienceRecipients } from './AudienceRecipients'

function recipient(email: string): RecipientApi {
    return {
        email,
        all_marketing: 'NO_PREFERENCE',
        topics: {},
        suppression: null,
        persons: [],
        person_count: 0,
        last_sent_at: null,
        preferences_updated_at: null,
    }
}

const FIRST_PAGE: RecipientPageApi = { results: [recipient('alex@example.com')], next_cursor: 'after-alex' }
const LAST_PAGE: RecipientPageApi = { results: [recipient('sam@example.com')], next_cursor: null }

describe('AudienceRecipients', () => {
    type MockResponse = [number, unknown]

    function useRecipientsResponse(respond: (params: URLSearchParams) => MockResponse | Promise<MockResponse>): void {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_recipients/': ({ request }) =>
                    respond(new URL(request.url).searchParams),
                '/api/projects/:team_id/messaging_recipients/coverage/': { persons_without_email: 0 },
            },
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the page controls on screen while the next page loads', async () => {
        let releaseLastPage = (): void => {}
        const lastPageReleased = new Promise<void>((resolve) => {
            releaseLastPage = resolve
        })
        useRecipientsResponse(async (params) => {
            if (params.get('cursor')) {
                await lastPageReleased
                return [200, LAST_PAGE]
            }
            return [200, FIRST_PAGE]
        })
        render(<AudienceRecipients />)

        fireEvent.click(await screen.findByLabelText('Next page'))

        expect(screen.getByLabelText('Next page')).toBeInTheDocument()
        releaseLastPage()
        expect(await screen.findByText('sam@example.com')).toBeInTheDocument()
    })

    it('names the missing permission instead of the search advice when access is denied', async () => {
        useRecipientsResponse(() => [403, { detail: 'You need hog_flow viewer access to view recipients.' }])
        render(<AudienceRecipients />)

        expect(await screen.findByText('Access denied')).toBeInTheDocument()
        expect(screen.getByText(/viewer access to Workflows/)).toBeInTheDocument()
        expect(screen.queryByText(/Search for part of an address/)).not.toBeInTheDocument()
    })
})
