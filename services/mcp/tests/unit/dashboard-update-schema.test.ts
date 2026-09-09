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
        const openapiBodyKeys = Object.keys(DashboardsPartialUpdateBody().shape)

        for (const param of openapiBodyKeys) {
            expect(toolShape[param], `dashboard-update schema missing OpenAPI field: ${param}`).not.toBeUndefined()
        }
    })

    it('accepts optional dashboard PATCH write params', () => {
        const result = tool.schema.safeParse({
            id: 1,
            breakdown_colors: [{ breakdownValue: 'Chrome', breakdownType: 'event', colorToken: 'preset-1' }],
            data_color_theme_id: 2,
            quick_filter_ids: ['00000000-0000-4000-8000-000000000001'],
            use_template: '',
            use_dashboard: null,
            delete_insights: false,
            tiles: [{ id: 1, widget: { config: { limit: 10 } } }],
        })

        expect(result.success).toBe(true)
    })

    // The schema used to accept any JSON for this field, and its description read as a color
    // mapping, so agents sent a dictionary of breakdown values to hex colors. The dashboard cannot
    // read that shape.
    it.each([
        ['an object keyed by breakdown value', { series_a: '#ff0000' }],
        ['entries under other key names', [{ breakdown_value: 'good', color: '#36a854' }]],
        ['an entry without a color token', [{ breakdownValue: 'Chrome' }]],
        ['a hex value where a palette slot belongs', [{ breakdownValue: 'Chrome', colorToken: '#3fb950' }]],
        // Also proves the generated schema carries the serializer's token pattern.
        ['palette slot zero', [{ breakdownValue: 'Chrome', colorToken: 'preset-0' }]],
    ])('rejects breakdown_colors as %s', (_name, breakdownColors) => {
        const result = tool.schema.safeParse({ id: 1, breakdown_colors: breakdownColors })

        expect(result.success).toBe(false)
    })
})
