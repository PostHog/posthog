import { useActions, useValues } from 'kea'
import { ReactElement, useMemo, useState } from 'react'

import {
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Spinner,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

import { InboxReportActionSurface } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { getReviewerOptionDisplayName } from './reviewerDisplay'
import { toggleSuggestedReviewer } from './suggestedReviewers'

/**
 * The quill sibling of `ReviewerSearchList`, for the report page behind `today-rail-nav`: a searchable
 * org-member picker, opened from `trigger`, that toggles a report's suggested reviewers.
 */
export function QuillReviewerSearchList({
    report,
    surface,
    trigger,
}: {
    report: SignalReport
    /** Which surface hosts the list, for the add/remove reviewer analytics. */
    surface: InboxReportActionSurface
    /** The button that opens the picker. */
    trigger: ReactElement
}): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, addReviewerOptions, availableReviewersLoading, isUpdatingReviewers, reportArtefacts } =
        useValues(logic)
    const { updateReviewers, searchAvailableReviewers } = useActions(logic)
    const searching = availableReviewersLoading || reportArtefacts === null
    const [query, setQuery] = useState('')

    const baseReviewers = displayReviewers ?? []
    const assignedUuids = baseReviewers.map((r) => r.user?.uuid).filter((uuid): uuid is string => !!uuid)
    const optionsByUuid = useMemo(
        () => new Map(addReviewerOptions.map((option) => [option.user_uuid, option])),
        [addReviewerOptions]
    )
    const meUuid = addReviewerOptions[0]?.user_uuid
    const displayName = (uuid: string): string => {
        const option = optionsByUuid.get(uuid)
        return option ? getReviewerOptionDisplayName(option, uuid === meUuid) : ''
    }

    return (
        <Combobox<string, true>
            multiple
            items={searching ? [] : addReviewerOptions.map((option) => option.user_uuid)}
            // The logic searches the members on the server, so the list shows its results as they are.
            filter={null}
            value={assignedUuids}
            inputValue={query}
            itemToStringLabel={displayName}
            onInputValueChange={(value, details) => {
                // Picking a row would clear the search otherwise, and the list would jump back to everyone.
                if (details.reason !== 'input-change') {
                    return
                }
                setQuery(value)
                searchAvailableReviewers(value)
            }}
            onValueChange={(next) => {
                const picked = new Set(next)
                const option = addReviewerOptions.find(
                    (o) => picked.has(o.user_uuid) !== assignedUuids.includes(o.user_uuid)
                )
                if (option) {
                    toggleSuggestedReviewer({ report, surface, option, reviewers: baseReviewers, updateReviewers })
                }
            }}
        >
            <ComboboxTrigger render={trigger} />
            <ComboboxContent align="end" className="w-72">
                <ComboboxInput placeholder="Search users…" autoFocus showTrigger={false} />
                <ComboboxEmpty>
                    {searching ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Searching…
                        </span>
                    ) : (
                        'No users found.'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(uuid: string) => {
                        const option = optionsByUuid.get(uuid)
                        return (
                            <ComboboxItem
                                key={uuid}
                                value={uuid}
                                disabledReason={isUpdatingReviewers ? 'Updating…' : undefined}
                            >
                                <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                    <QuillPersonAvatar name={option?.name ?? ''} email={option?.email} size="xs" />
                                    <span className="truncate">{displayName(uuid)}</span>
                                </span>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
