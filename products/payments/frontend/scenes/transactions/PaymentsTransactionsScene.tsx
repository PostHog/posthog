import { useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { PaymentsTabs } from '../../components/PaymentsTabs'
import { paymentsTransactionsLogic } from './paymentsTransactionsLogic'

export function PaymentsTransactionsScene(): JSX.Element {
    const logic = paymentsTransactionsLogic()
    const { transactions } = useValues(logic)

    return (
        <>
            <PaymentsTabs />
            <h1>Transactions</h1>
            <LemonTable
                columns={[
                    {
                        dataIndex: 'amount',
                        title: 'Amount',
                    },
                    {
                        dataIndex: 'currency',
                        title: 'Currency',
                    },
                    {
                        dataIndex: 'description',
                        title: 'Description',
                    },
                    {
                        dataIndex: 'created',
                        title: 'Date',
                    },
                ]}
                dataSource={transactions}
            />
        </>
    )
}
