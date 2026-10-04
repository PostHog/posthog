import { getMessagingRecipientsRetrieveUrl } from './generated/api'

describe('messaging recipients api', () => {
    it('sends every filter as its own query parameter', () => {
        const url = getMessagingRecipientsRetrieveUrl('1', {
            filter: ['subscribed:newsletter', '-suppressed:BOUNCE'],
        })

        expect(new URL(url, 'http://localhost').searchParams.getAll('filter')).toEqual([
            'subscribed:newsletter',
            '-suppressed:BOUNCE',
        ])
    })
})
