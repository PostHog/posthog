import { sidebarProductMeta } from '~/layout/panel-layout/sidebarProductMeta'
import { destinationRecentsFromViews } from '~/layout/today/todayAutomate'
import { paneProducts } from '~/layout/today/todayPaneProducts'
import { TODAY_PRODUCT_PANES, productPaneConfig } from '~/layout/today/todayProductPanes'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { activePaneRow, paneRecentRows } from './todayProductPaneLogic'

describe('todayProductPaneLogic', () => {
    test.each(TODAY_PRODUCT_PANES.map((config) => [config.pane, config] as const))(
        'marks exactly one row active on each %s page',
        (_, config) => {
            const { lead, sections } = paneProducts(config)
            const products = [...lead, ...sections.flatMap((section) => section.products)]
            const activeRows = products.map((product) => activePaneRow(config, `/project/1${product.href}`, null, []))

            expect(activeRows).toEqual(products.map((product) => `product:${product.key}`))
            expect(new Set(activeRows).size).toBe(products.length)
        }
    )

    it('gives every Automate row a hover description', () => {
        const missing = paneProducts(productPaneConfig('automate')).lead.filter(
            (product) => !sidebarProductMeta(product.item).description
        )
        expect(missing.map((product) => product.label)).toEqual([])
    })

    it('adds viewed destinations to the pane recents once each, skips ones never opened, and sorts by name', () => {
        const opened = { type: 'hog_function/destination' as const, name: 'Slack alerts', href: '/functions/a' }
        const viewed = (ref: string, name: string, lastViewedAt?: string): FileSystemEntry => ({
            id: ref,
            path: `Unfiled/Destinations/${name}`,
            type: 'hog_function/destination',
            ref,
            last_viewed_at: lastViewedAt,
        })

        const recents = paneRecentRows(
            [opened],
            destinationRecentsFromViews([
                viewed('a', 'Slack alerts', '2026-11-20T10:00:00Z'),
                viewed('b', 'Audit log export', '2026-11-19T10:00:00Z'),
                viewed('c', 'Never opened'),
            ])
        )

        expect(recents.map((recent) => recent.href)).toEqual(['/functions/b', '/functions/a'])
    })
})
