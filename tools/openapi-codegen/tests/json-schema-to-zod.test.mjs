import { describe, expect, it } from 'vitest'

import { generateZodFromOpenApiComponent } from '../src/json-schema-to-zod.mjs'

describe('generateZodFromOpenApiComponent', () => {
    it('emits limit min/max and default from widget config schema', () => {
        const componentSchemas = {
            ErrorTrackingListWidgetConfig: {
                type: 'object',
                properties: {
                    limit: {
                        type: 'integer',
                        minimum: 1,
                        maximum: 25,
                        default: 10,
                    },
                },
            },
        }

        const { body } = generateZodFromOpenApiComponent(componentSchemas, 'ErrorTrackingListWidgetConfig')
        expect(body).toContain('zod.number().int().min(1).max(25)')
        expect(body).toContain('.default(10)')
    })
})
