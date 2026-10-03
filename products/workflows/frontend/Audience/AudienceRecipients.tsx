import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { RecipientsBody } from './RecipientsBody'
import { RECIPIENT_SEARCH_MAX_LENGTH, recipientsLogic } from './recipientsLogic'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

export function AudienceRecipients(): JSX.Element {
    const { search, loadFailed, recipientsView } = useValues(recipientsLogic)
    const { setSearch, clearSearch, retryLoadRecipients } = useActions(recipientsLogic)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const thenFocusSearch = (action: () => void) => (): void => {
        action()
        searchInputRef.current?.focus()
    }

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="audience-recipients">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search by email address"
                    aria-label="Search recipients by email address"
                    inputRef={searchInputRef}
                    value={search}
                    maxLength={RECIPIENT_SEARCH_MAX_LENGTH}
                    onChange={setSearch}
                    className="flex-1 max-w-100"
                    data-attr="audience-recipients-search"
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGear />}
                    to={urls.audienceSetup()}
                    data-attr="audience-recipients-set-up"
                >
                    Set up
                </LemonButton>
            </div>
            <UnreachablePersonsNotice />
            {loadFailed && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: thenFocusSearch(retryLoadRecipients),
                        'data-attr': 'audience-recipients-retry',
                    }}
                >
                    {recipientsView === 'results'
                        ? "Couldn't load that page of recipients. Try again in a moment."
                        : "Couldn't load recipients. Search for part of an address to load fewer, or try again in a moment."}
                </LemonBanner>
            )}
            <RecipientsBody onClearSearch={thenFocusSearch(clearSearch)} />
        </div>
    )
}
