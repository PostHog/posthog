import { actions, afterMount, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import posthog from 'posthog-js'

import { paymentsProductsLogicType } from './paymentsProductsLogicType'

export const paymentsProductsLogic = kea<paymentsProductsLogicType>([
    path((key) => ['scenes', 'payments', 'products', 'paymentsProductsLogic', key]),
    props({}),
    actions(() => ({
        loadProducts: true,
        loadPrices: true,
        setProducts: (products: any) => ({ products }),
        setPrices: (prices: any) => ({ prices }),
    })),
    reducers(() => ({
        products: [
            [],
            {
                setProducts: (_, { products }) => products,
            },
        ],
        prices: [
            [],
            {
                setPrices: (_, { prices }) => prices,
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadProducts: async () => {
            try {
                const response = await api.payments.listProducts()
                if (response.data) {
                    actions.setProducts(response.data)
                }
            } catch (e) {
                posthog.captureException(e, { posthog_feature: 'payments_products' })
            }
        },
        loadPrices: async () => {
            try {
                const response = await api.payments.listPrices()
                if (response.data) {
                    actions.setPrices(response.data)
                }
            } catch (e) {
                posthog.captureException(e, { posthog_feature: 'payments_prices' })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProducts()
        actions.loadPrices()
    }),
])
