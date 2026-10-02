import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { recipientsLogic } from './recipientsLogic'
import { RecipientsTable } from './RecipientsTable'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

function RecipientsBody(): JSX.Element {
    const { recipientsView } = useValues(recipientsLogic)
    const { setSearch, retryLoadRecipients } = useActions(recipientsLogic)

    switch (recipientsView) {
        case 'error':
            return (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: retryLoadRecipients,
                        'data-attr': 'audience-recipients-retry',
                    }}
                >
                    Couldn't load recipients. Try a narrower search, or try again in a moment.
                </LemonBanner>
            )
        case 'empty':
            return (
                <EmptyMessage
                    title="No recipients yet"
                    description="An address shows up here once your app records a topic preference for it, it's added to the suppression list, or a person has it as their email property."
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

export function AudienceRecipients(): JSX.Element {
    const { search } = useValues(recipientsLogic)
    const { setSearch } = useActions(recipientsLogic)

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="audience-recipients">
            <LemonInput
                type="search"
                placeholder="Search by email address"
                value={search}
                onChange={setSearch}
                className="max-w-100"
                data-attr="audience-recipients-search"
            />
            <UnreachablePersonsNotice />
            <RecipientsBody />
        </div>
    )
}
