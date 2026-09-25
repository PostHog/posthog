import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/conversations'

// Both ticket-read tools take the ticket identifier as a bare `id`, but the
// surrounding vocabulary calls it a ticket: sibling params are named
// `message_id`, the list response carries `ticket_number`, and triage prose
// says "ticket id" throughout. Agents composing a call guess `ticket_id`, or
// send the documented numeric ticket number as a JSON number. Both name a real
// ticket, and both used to fail validation before the request was ever sent.
describe('conversations ticket id aliases and numeric ticket numbers', () => {
    const TICKET_UUID = '01a0b547-5dc0-0000-9fe7-4f2dbcf2733b'

    describe.each(['conversations-tickets-retrieve', 'conversations-tickets-messages-retrieve'] as const)(
        '%s',
        (toolName) => {
            const schema = GENERATED_TOOLS[toolName]!().schema

            it.each([
                ['id (the documented key)', { id: TICKET_UUID }, TICKET_UUID],
                ['ticket_id', { ticket_id: TICKET_UUID }, TICKET_UUID],
                ['ticketId', { ticketId: TICKET_UUID }, TICKET_UUID],
                ['ticket_number', { ticket_number: 12345 }, '12345'],
                ['ticketNumber', { ticketNumber: '12345' }, '12345'],
                ['a numeric ticket number as a JSON number', { id: 12345 }, '12345'],
                ['id over an alias on conflict', { id: TICKET_UUID, ticket_id: 'other' }, TICKET_UUID],
            ])('accepts %s and normalizes it to a string `id`', (_label, input, expected) => {
                const result = schema.safeParse(input)
                expect(result.success).toBe(true)
                const data = result.data as Record<string, unknown>
                expect(data.id).toBe(expected)
                expect(data).not.toHaveProperty('ticket_id')
                expect(data).not.toHaveProperty('ticket_number')
            })

            it('still rejects a call with no identifier', () => {
                expect(schema.safeParse({}).success).toBe(false)
            })

            it('still rejects an identifier that names no ticket', () => {
                // A fractional id cannot be a ticket number or a UUID, so it must
                // keep failing rather than being coerced into a lookup.
                expect(schema.safeParse({ id: 1.5 }).success).toBe(false)
            })
        }
    )
})
