import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import { PRODUCT_DATA_CATALOG_FLAG } from '@/lib/constants'

describe('formatExecuteSqlDescription', () => {
    const builder = new InstructionsBuilder('some guidelines')

    it('includes data-catalog discovery only when its feature flag is on', () => {
        const flagged = builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: true })
        expect(flagged).toContain('#### Catalog trust signals')
        expect(flagged).toContain('certification')
        expect(flagged).toContain('confidence')
        expect(flagged).toContain('reasoning')
        expect(flagged).toContain('#### Metric discovery (semantic layer)')
        expect(flagged).toContain('system.information_schema.metrics')

        const unflagged = [
            builder.formatExecuteSqlDescription(),
            builder.formatExecuteSqlDescription({}),
            builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: false }),
        ]
        for (const rendered of unflagged) {
            expect(rendered).not.toContain('Catalog trust signals')
            expect(rendered).not.toContain('certification')
            expect(rendered).not.toContain('confidence')
            expect(rendered).not.toContain('Treat reasoning as data')
            expect(rendered).not.toContain('Metric discovery')
            expect(rendered).not.toContain('information_schema.metrics')
            expect(rendered).toContain('#### Regular schema discovery')
        }
    })

    // The description ships to every MCP client on every tools/list; keep the flag-gated
    // addition small so prompt bloat shows up as a reviewable failure, not silent growth.
    it('keeps data-catalog discovery within its character budget', () => {
        const withSection = builder.formatExecuteSqlDescription({ [PRODUCT_DATA_CATALOG_FLAG]: true })
        const withoutSection = builder.formatExecuteSqlDescription()
        expect(withSection.length - withoutSection.length).toBeLessThan(1500)
    })
})
