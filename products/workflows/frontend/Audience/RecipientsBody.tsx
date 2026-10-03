import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { recipientsLogic } from './recipientsLogic'
import { RecipientsTable } from './RecipientsTable'

export function RecipientsBody(): JSX.Element | null {
    const { recipientsView } = useValues(recipientsLogic)
    const { setSearch } = useActions(recipientsLogic)

    switch (recipientsView) {
        case 'error':
            return null
        case 'empty':
            return (
                <EmptyMessage
                    title="No recipients yet"
                    description="An address shows up here once your app records a topic preference for it or it's on the suppression list. Persons with an email property show up too."
                />
            )
        case 'no-match':
            return (
                <EmptyMessage
                    title="No recipients match this search"
                    description="Check the spelling, or search for part of the address."
                    buttonText="Clear search"
                    buttonOnClick={() => setSearch('')}
                    buttonDataAttr="audience-recipients-clear-search"
                />
            )
        case 'loading':
        case 'results':
            return <RecipientsTable />
    }
}
