import { MakeLogicType, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'

import { accountsList, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'

interface AccountChoices {
    options: { key: string; label: string }[]
    failed: boolean
}
interface AccountQuery {
    query: string
    accountId: string | null
}
interface AccountLogicProps {
    id: string
    projectId: number | null
}

export interface customerTaskWorkflowAccountLogicValues {
    choices: AccountChoices | null
    choicesLoading: boolean
}
export interface customerTaskWorkflowAccountLogicActions {
    loadChoices: (query: AccountQuery) => AccountQuery
    loadChoicesSuccess: (
        choices: AccountChoices | null,
        payload?: AccountQuery
    ) => { choices: AccountChoices | null; payload?: AccountQuery }
    loadChoicesFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
}
export type customerTaskWorkflowAccountLogicType = MakeLogicType<
    customerTaskWorkflowAccountLogicValues,
    customerTaskWorkflowAccountLogicActions,
    AccountLogicProps,
    { key: string }
>

export const customerTaskWorkflowAccountLogic = kea<customerTaskWorkflowAccountLogicType>([
    path([
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'steps',
        'components',
        'customerTaskWorkflowAccountLogic',
    ]),
    props({} as AccountLogicProps),
    key(({ id, projectId }) => `${id}:${projectId}`),
    loaders(({ props }) => ({
        choices: [
            null as AccountChoices | null,
            {
                loadChoices: async ({ query, accountId }: AccountQuery, breakpoint): Promise<AccountChoices> => {
                    await breakpoint(300)
                    if (props.projectId === null) {
                        return { options: [], failed: false }
                    }
                    try {
                        const response = await accountsList(String(props.projectId), {
                            search: query || undefined,
                            limit: 25,
                        })
                        breakpoint()
                        const options = response.results.map((account) => ({ key: account.id, label: account.name }))
                        if (accountId && !options.some((option) => option.key === accountId)) {
                            try {
                                const selected = await accountsRetrieve(String(props.projectId), accountId)
                                breakpoint()
                                options.unshift({ key: selected.id, label: selected.name })
                            } catch (error) {
                                breakpoint()
                                // Only a 404 proves the saved account is really gone. Any other failure
                                // leaves that unanswered, so report it as retryable instead of letting the
                                // picker advise replacing an account that is probably still valid.
                                if (!(error instanceof ApiError) || error.status !== 404) {
                                    return { options: [], failed: true }
                                }
                            }
                        }
                        return { options, failed: false }
                    } catch {
                        breakpoint()
                        return { options: [], failed: true }
                    }
                },
            },
        ],
    })),
])
