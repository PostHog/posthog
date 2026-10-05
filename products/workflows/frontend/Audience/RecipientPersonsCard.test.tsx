import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { RecipientApi, RecipientPersonApi } from 'products/messaging/frontend/generated/api.schemas'

import { RecipientPersonsCard } from './RecipientPersonsCard'
import { recipient } from './recipientTestFixtures'

function recipientWith(personCount: number, persons: Partial<RecipientPersonApi>[]): RecipientApi {
    return recipient('alex@example.com', {
        person_count: personCount,
        persons: persons.map((person, index) => ({ uuid: `person-${index}`, distinct_id: '', name: null, ...person })),
    })
}

describe('RecipientPersonsCard', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'a person with a blank name',
            recipient: recipientWith(1, [{ name: '  ', distinct_id: 'user-42' }]),
            shown: ['user-42'],
        },
        { name: 'a person with no name or distinct ID', recipient: recipientWith(1, [{}]), shown: ['Unnamed person'] },
        {
            name: 'more persons than listed',
            recipient: recipientWith(1342, [{ name: 'Alex Rivera', distinct_id: 'alex-web' }]),
            shown: ['Alex Rivera', 'alex-web', 'and 1,341 more persons'],
        },
    ])('links the first label to the person and shows each label once for $name', ({ recipient, shown }) => {
        render(<RecipientPersonsCard recipient={recipient} />)

        expect(screen.getByText(shown[0]).closest('a')).toHaveAttribute('href', expect.stringContaining('person-0'))
        for (const text of shown) {
            expect(screen.getAllByText(text)).toHaveLength(1)
        }
    })
})
