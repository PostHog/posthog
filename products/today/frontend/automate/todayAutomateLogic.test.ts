import { sidebarProductMeta } from '~/layout/panel-layout/sidebarProductMeta'
import { automateProducts } from '~/layout/today/todayAutomate'

import { activeAutomateRow } from './todayAutomateLogic'

describe('todayAutomateLogic', () => {
    it('marks exactly one row active on each Automate page', () => {
        const products = automateProducts()
        const activeRows = products.map((product) => activeAutomateRow(`/project/1${product.href}`, null, []))

        expect(activeRows).toEqual(products.map((product) => `product:${product.key}`))
        expect(new Set(activeRows).size).toBe(products.length)
    })

    it('gives every Automate row a hover description', () => {
        const missing = automateProducts().filter((product) => !sidebarProductMeta(product.item).description)
        expect(missing.map((product) => product.label)).toEqual([])
    })
})
