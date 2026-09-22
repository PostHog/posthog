import { buildDecideRequest, parseCriteria } from './decisionPlaygroundLogic'

describe('decisionPlaygroundLogic request building', () => {
    it.each([
        [
            'billing: payments, invoices\nsupport: product questions',
            { billing: 'payments, invoices', support: 'product questions' },
        ],
        ['  yes  \n\nno', { yes: 'yes', no: 'no' }],
        ['', undefined],
    ])('parses criteria lines %p', (criteria, expected) => {
        expect(parseCriteria(criteria)).toEqual(expected)
    })

    it('sends criteria only for questions that take options', () => {
        const body = buildDecideRequest('ticket text', [
            { key: 'k1', id: 'urgent', type: 'noul', instructions: 'Urgent?', criteria: 'stale: ignored' },
            { key: 'k2', id: 'queue', type: 'choice', instructions: 'Which team?', criteria: 'billing: money' },
        ])

        expect(body).toEqual({
            state: 'ticket text',
            questions: {
                urgent: { type: 'noul', instructions: 'Urgent?' },
                queue: { type: 'choice', instructions: 'Which team?', criteria: { billing: 'money' } },
            },
        })
    })
})
