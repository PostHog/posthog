import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { FacetSearchBar } from 'lib/components/FacetSearchBar/FacetSearchBar'

import { recipientsLogic } from './recipientsLogic'
import { RecipientsTable } from './RecipientsTable'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

function LoadFailedBanner(): JSX.Element {
    const { retryLoadRecipients } = useActions(recipientsLogic)
    return (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: retryLoadRecipients, 'data-attr': 'audience-recipients-retry' }}
        >
            Couldn't load recipients. Search for part of an address to load fewer, or try again in a moment.
        </LemonBanner>
    )
}

function RecipientsBody(): JSX.Element {
    const { recipientsView, loadFailed } = useValues(recipientsLogic)
    const { clearSearch } = useActions(recipientsLogic)

    switch (recipientsView) {
        case 'error':
            return <LoadFailedBanner />
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
                    description="Check the spelling, search for part of the address, or remove a filter."
                    buttonText="Clear search and filters"
                    buttonOnClick={clearSearch}
                    buttonDataAttr="audience-recipients-clear-search"
                />
            )
        case 'loading':
        case 'results':
            return (
                <>
                    {loadFailed && <LoadFailedBanner />}
                    <RecipientsTable />
                </>
            )
    }
}

export function AudienceRecipients(): JSX.Element {
    const { facets, searchValue } = useValues(recipientsLogic)
    const { setSearchValue } = useActions(recipientsLogic)

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="audience-recipients">
            <div className="max-w-160">
                <FacetSearchBar
                    facets={facets}
                    value={searchValue}
                    onChange={setSearchValue}
                    placeholder="Search by address, or filter by topic, suppression or person"
                    dataAttr="audience-recipients-search"
                />
            </div>
            <UnreachablePersonsNotice />
            <RecipientsBody />
        </div>
    )
}
