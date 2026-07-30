import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import { PRODUCT_DATA_CATALOG_FLAG } from '@/lib/constants'

describe('formatExecuteSqlDescription', () => {
    const builder = new InstructionsBuilder('some guidelines')

    it('includes the metric-discovery section only when the data-catalog flag is on', () => {
        const flagged = builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: true })
        expect(flagged).toContain('#### Metric discovery (semantic layer)')
        expect(flagged).toContain('system.information_schema.metrics')

        const unflagged = [
            builder.formatExecuteSqlDescription(),
            builder.formatExecuteSqlDescription({}),
            builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: false }),
        ]
        for (const rendered of unflagged) {
            expect(rendered).not.toContain('Metric discovery')
            expect(rendered).not.toContain('information_schema.metrics')
            expect(rendered).toContain('#### Regular schema discovery')
        }
    })

    // The description ships to every MCP client on every tools/list; keep the flag-gated
    // addition small so prompt bloat shows up as a reviewable failure, not silent growth.
    it('keeps the metric-discovery section within its character budget', () => {
        const withSection = builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: true })
        const withoutSection = builder.formatExecuteSqlDescription()
        expect(withSection.length - withoutSection.length).toBeLessThan(1200)
    })
})
