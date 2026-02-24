import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import readDataSchemaTool from '@/tools/posthogAiTools/readDataSchema'
import type { Context } from '@/tools/types'

describe('read-data-schema', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    const tool = readDataSchemaTool()

    it('should list available events', async () => {
        const result = await tool.handler(context, { query: { kind: 'events' } })

        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
        // $pageview is a system event captured by default
        expect(result).toContain('$pageview')
    })

    it('should return properties for $pageview event', async () => {
        const result = await tool.handler(context, {
            query: { kind: 'event_properties', event_name: '$pageview' },
        })

        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
    })

    it('should return person entity properties', async () => {
        const result = await tool.handler(context, {
            query: { kind: 'entity_properties', entity: 'person' },
        })

        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
    })

    it('should return sample property values for an event property', async () => {
        const result = await tool.handler(context, {
            query: {
                kind: 'event_property_values',
                event_name: '$pageview',
                property_name: '$browser',
            },
        })

        expect(typeof result).toBe('string')
    })

    it('should return sample property values for a person property', async () => {
        const result = await tool.handler(context, {
            query: {
                kind: 'entity_property_values',
                entity: 'person',
                property_name: 'email',
            },
        })

        expect(typeof result).toBe('string')
    })

    it('should handle a non-existent event name gracefully', async () => {
        const result = await tool.handler(context, {
            query: { kind: 'event_properties', event_name: 'definitely_does_not_exist_xyz_12345' },
        })

        expect(typeof result).toBe('string')
    })
})
