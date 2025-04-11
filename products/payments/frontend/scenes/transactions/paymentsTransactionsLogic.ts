import { actions, afterMount, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import posthog from 'posthog-js'

import { paymentsTransactionsLogicType } from './paymentsTransactionsLogicType'

export const paymentsTransactionsLogic = kea<paymentsTransactionsLogicType>([
    path((key) => ['scenes', 'payments', 'transactions', 'paymentsTransactionsLogic', key]),
    props({}),
    actions(() => ({
        loadTransactions: true,
        setTransactions: (transactions: any) => ({ transactions }),
    })),
    reducers(() => ({
        transactions: [
            [],
            {
                setTransactions: (_, { transactions }) => transactions,
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadTransactions: async () => {
            try {
                const response = await api.payments.listBalanceTransactions()
                if (response.data) {
                    actions.setTransactions(response.data)
                }
            } catch (e) {
                posthog.captureException(e, { posthog_feature: 'payments_transactions' })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTransactions()
    }),
])
