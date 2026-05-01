import { beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/conversations'
import type { Context } from '@/tools/types'

describe('Conversations', { concurrent: false }, () => {
    let context: Context

    const listTool = GENERATED_TOOLS['conversations-tickets-list']!()
    const getTool = GENERATED_TOOLS['conversations-tickets-retrieve']!()
    const updateTool = GENERATED_TOOLS['conversations-tickets-update']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('conversations-tickets-list tool', () => {
        it('should return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
            expect(typeof data._posthogUrl).toBe('string')
            expect(data._posthogUrl).toContain('/conversations/tickets')
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })

        it('should only include expected fields in list response', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            if (data.results.length > 0) {
                const ticket = data.results[0]
                expect(ticket).toHaveProperty('id')
                expect(ticket).toHaveProperty('ticket_number')
                expect(ticket).toHaveProperty('status')
                expect(ticket).not.toHaveProperty('anonymous_traits')
                expect(ticket).not.toHaveProperty('session_context')
                expect(ticket).not.toHaveProperty('person')
                expect(ticket).not.toHaveProperty('slack_channel_id')
                expect(ticket).not.toHaveProperty('distinct_id')
            }
        })
    })

    describe('conversations-tickets-retrieve tool', () => {
        it('should retrieve an existing ticket by ID', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listData = parseToolResponse(listResult)

            if (listData.results.length === 0) {
                return
            }

            const ticketId = listData.results[0].id
            const result = await getTool.handler(context, { id: ticketId })
            const data = parseToolResponse(result)

            expect(data.id).toBe(ticketId)
            expect(typeof data.ticket_number).toBe('number')
            expect(typeof data.status).toBe('string')
            expect(data).toHaveProperty('channel_source')
            expect(data).toHaveProperty('created_at')
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(getTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('conversations-tickets-update tool', () => {
        it('should update ticket status', async () => {
            const listResult = await listTool.handler(context, { limit: 1 })
            const listData = parseToolResponse(listResult)

            if (listData.results.length === 0) {
                return
            }

            const ticketId = listData.results[0].id
            const originalStatus = listData.results[0].status

            const newStatus = originalStatus === 'open' ? 'pending' : 'open'
            const updateResult = await updateTool.handler(context, { id: ticketId, status: newStatus })
            const updated = parseToolResponse(updateResult)

            expect(updated.status).toBe(newStatus)

            // Restore original status
            await updateTool.handler(context, { id: ticketId, status: originalStatus })
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(updateTool.handler(context, { id: absentId, status: 'open' })).rejects.toThrow()
        })
    })
})
