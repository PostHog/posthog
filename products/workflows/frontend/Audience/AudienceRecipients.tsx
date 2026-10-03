import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonBanner, LemonInput } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'

import { RecipientsBody } from './RecipientsBody'
import { RECIPIENT_SEARCH_MAX_LENGTH, recipientsLogic } from './recipientsLogic'
import { UnreachablePersonsNotice } from './UnreachablePersonsNotice'

export function AudienceRecipients(): JSX.Element {
    const { search, loadFailed, accessDenied } = useValues(recipientsLogic)
    const { setSearch, clearSearch, retryLoadRecipients } = useActions(recipientsLogic)
    const searchInputRef = useRef<HTMLInputElement>(null)
    const thenFocusSearch = (action: () => void) => (): void => {
        action()
        searchInputRef.current?.focus()
    }

    if (accessDenied) {
        return <AccessDenied reason="You need viewer access to Workflows to see recipients." inline />
    }

    return (
        <div className="flex flex-col gap-3 min-w-0" data-attr="audience-recipients">
            <LemonInput
                type="search"
                placeholder="Search by email address"
                aria-label="Search recipients by email address"
                inputRef={searchInputRef}
                value={search}
                maxLength={RECIPIENT_SEARCH_MAX_LENGTH}
                onChange={setSearch}
                className="max-w-100"
                data-attr="audience-recipients-search"
            />
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
                    Couldn't load recipients. Search for part of an address to load fewer, or try again in a moment.
                </LemonBanner>
            )}
            <RecipientsBody onClearSearch={thenFocusSearch(clearSearch)} />
        </div>
    )
}
