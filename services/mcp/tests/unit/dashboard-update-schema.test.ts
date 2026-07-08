import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { DashboardsPartialUpdateBody } from '@/generated/dashboards/api'
import { GENERATED_TOOLS } from '@/tools/generated/dashboards'

function getSchemaShape(schema: z.ZodTypeAny): Record<string, z.ZodTypeAny> {
    if ('shape' in schema && schema.shape && typeof schema.shape === 'object') {
        return schema.shape as Record<string, z.ZodTypeAny>
    }
    const inner = (schema._def as { schema?: z.ZodTypeAny }).schema
    if (inner) {
        return getSchemaShape(inner)
    }
    throw new Error(`Expected object schema, got ${schema.constructor.name}`)
}

describe('dashboard-update schema', () => {
    const tool = GENERATED_TOOLS['dashboard-update']!()

    it('includes every OpenAPI PATCH body field from DashboardsPartialUpdateBody', () => {
        const toolShape = getSchemaShape(tool.schema)
        const openapiBodyKeys = Object.keys(DashboardsPartialUpdateBody.shape)

        for (const param of openapiBodyKeys) {
            expect(toolShape[param], `dashboard-update schema missing OpenAPI field: ${param}`).not.toBeUndefined()
        }
    })

    it('accepts optional dashboard PATCH write params', () => {
        const result = tool.schema.safeParse({
            id: 1,
            breakdown_colors: { series_a: '#ff0000' },
            data_color_theme_id: 2,
            quick_filter_ids: ['00000000-0000-4000-8000-000000000001'],
            use_template: '',
            use_dashboard: null,
            delete_insights: false,
            tiles: [{ id: 1, widget: { config: { limit: 10 } } }],
        })

        expect(result.success).toBe(true)
    })
})
