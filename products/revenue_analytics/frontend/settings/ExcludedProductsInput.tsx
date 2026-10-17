import { useValues } from 'kea'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { ExternalDataSource } from '~/types'

import { excludedProductsLogic } from './excludedProductsLogic'

export interface ExcludedProductsInputProps {
    source: ExternalDataSource
    disabledReason?: string
    onChange: (excludedProductIds: string[]) => void
}

export function ExcludedProductsInput({ source, disabledReason, onChange }: ExcludedProductsInputProps): JSX.Element {
    const { products, productsLoading } = useValues(excludedProductsLogic({ source }))

    return (
        <div className="flex flex-col gap-1 px-4 py-3 max-w-192">
            <span className="font-semibold">Excluded products</span>
            <span className="text-secondary">
                Invoice lines for these Stripe products are left out of revenue analytics. Use this for a product that
                other invoices already count, such as prepaid credit that later pays for those invoices. Charges without
                an invoice are not affected.
            </span>
            <LemonInputSelect
                mode="multiple"
                allowCustomValues
                size="small"
                data-attr="revenue-analytics-excluded-products"
                loading={productsLoading}
                options={(products ?? []).map((product) => ({
                    key: product.id,
                    label: product.name === product.id ? product.id : `${product.name} (${product.id})`,
                }))}
                placeholder="Select a product or enter a Stripe product ID, for example prod_123"
                value={source.revenue_analytics_config.excluded_product_ids ?? []}
                disabledReason={disabledReason}
                onChange={onChange}
            />
        </div>
    )
}
