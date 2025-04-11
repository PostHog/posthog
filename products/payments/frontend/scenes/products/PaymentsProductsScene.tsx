import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { PaymentsTabs } from '../../components/PaymentsTabs'
import { paymentsProductsLogic } from './paymentsProductsLogic'

export function PaymentsProductsScene(): JSX.Element {
    const logic = paymentsProductsLogic()
    const { products } = useValues(logic)

    return (
        <>
            <PaymentsTabs />
            <h1>Products</h1>
            <LemonTable
                columns={[
                    {
                        dataIndex: 'id',
                        title: 'Product ID',
                    },
                    {
                        dataIndex: 'name',
                        title: 'Name',
                    },
                    {
                        dataIndex: 'default_price',
                        title: 'Price',
                    },
                    {
                        dataIndex: 'active',
                        title: 'Status',
                    },
                ]}
                dataSource={products}
            />
        </>
    )
}
