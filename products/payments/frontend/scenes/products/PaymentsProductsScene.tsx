import { LemonTable } from '@posthog/lemon-ui'

import { PaymentsTabs } from '../../components/PaymentsTabs'

export function PaymentsProductsScene(): JSX.Element {
    return (
        <>
            <PaymentsTabs />
            <h1>Products</h1>
            <LemonTable
                columns={[
                    {
                        dataIndex: 'product_id',
                        title: 'Product ID',
                    },
                    {
                        dataIndex: 'name',
                        title: 'Name',
                    },
                    {
                        dataIndex: 'price',
                        title: 'Price',
                    },
                    {
                        dataIndex: 'status',
                        title: 'Status',
                    },
                ]}
                dataSource={[
                    {
                        product_id: 'phpr_prod_1',
                        name: 'Product 1',
                        price: 100,
                        status: 'active',
                    },
                    {
                        product_id: 'phpr_prod_2',
                        name: 'Product 2',
                        price: 200,
                        status: 'inactive',
                    },
                ]}
            />
        </>
    )
}
