import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { RecipientApi, RecipientPersonApi } from 'products/messaging/frontend/generated/api.schemas'

import { RecipientPersonsSummary } from './RecipientPersonsSummary'
import { recipient } from './recipientTestFixtures'

function recipientWith(personCount: number, persons: Partial<RecipientPersonApi>[]): RecipientApi {
    return recipient('alex@example.com', {
        person_count: personCount,
        persons: persons.map((person) => ({ uuid: 'person-1', distinct_id: '', name: null, ...person })),
    })
}

describe('RecipientPersonsSummary', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        { name: 'no person', recipient: recipientWith(0, []), shown: 'No person' },
        { name: 'a named person', recipient: recipientWith(1, [{ name: 'Alex Rivera' }]), shown: 'Alex Rivera' },
        {
            name: 'a person with a blank name',
            recipient: recipientWith(1, [{ name: '  ', distinct_id: 'user-42' }]),
            shown: 'user-42',
        },
        { name: 'a person with no name or distinct ID', recipient: recipientWith(1, [{}]), shown: '1 person' },
        { name: 'several persons', recipient: recipientWith(1342, [{}, {}, {}]), shown: '1,342 persons' },
    ])('shows $shown for $name', ({ recipient, shown }) => {
        render(<RecipientPersonsSummary recipient={recipient} />)

        expect(screen.getByText(shown)).toBeInTheDocument()
    })
})
