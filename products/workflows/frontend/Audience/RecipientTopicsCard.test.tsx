import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'

import { recipient } from './recipientTestFixtures'
import { RecipientTopicsCard } from './RecipientTopicsCard'

function topic(key: string, name: string, categoryType: MessageCategoryApi['category_type']): MessageCategoryApi {
    return {
        id: `topic-${key}`,
        key,
        name,
        description: '',
        public_description: '',
        category_type: categoryType,
        created_at: '2026-09-01T10:00:00Z',
        updated_at: '2026-09-01T10:00:00Z',
        created_by: null,
    }
}

const TOPICS = [
    topic('newsletter', 'Newsletter', 'marketing'),
    topic('constructor', 'Builders club', 'marketing'),
    topic('receipts', 'Receipts', 'transactional'),
    topic('password-resets', 'Password resets', 'transactional'),
]

describe('RecipientTopicsCard', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/projects/:team_id/messaging_categories/': { results: TOPICS, next: null } } })
    })

    afterEach(() => {
        cleanup()
    })

    it('lists every marketing topic and only the transactional topics the recipient has a status for', async () => {
        render(
            <RecipientTopicsCard
                recipient={recipient('jamie@example.com', {
                    all_marketing: 'OPTED_IN',
                    topics: { newsletter: 'OPTED_OUT', receipts: 'OPTED_OUT' },
                    preferences_updated_at: '2026-09-20T08:30:00Z',
                })}
            />
        )

        const rows = await screen.findAllByTestId('audience-recipient-topic')
        expect(rows.map((row) => row.textContent)).toEqual([
            'All marketingEvery marketing topic at onceSubscribed',
            'NewsletterUnsubscribed',
            'Builders clubNo preference',
            'ReceiptsUnsubscribed',
        ])
        expect(screen.getByText(/Last changed/)).toBeInTheDocument()
    })
})
