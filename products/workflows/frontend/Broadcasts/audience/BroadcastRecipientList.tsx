import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { broadcastWizardLogic } from '../broadcastWizardLogic'

/** The uploaded recipient list a broadcast sends to: how many rows it holds and the columns the email can use. */
export function BroadcastRecipientList(): JSX.Element {
    const { recipientList, recipientListLoading } = useValues(broadcastWizardLogic)
    const { removeRecipientList } = useActions(broadcastWizardLogic)

    if (recipientListLoading) {
        return <Spinner />
    }

    const dropped = recipientList
        ? [
              { count: recipientList.dropped_invalid_email, reason: 'with an invalid email' },
              { count: recipientList.dropped_duplicate_email, reason: 'with a duplicate email' },
              { count: recipientList.dropped_too_large, reason: 'with more than 4KB of data' },
          ].filter(({ count }) => count > 0)
        : []

    return (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-primary p-3">
            <div className="flex items-start justify-between gap-2">
                {recipientList ? (
                    <span className="font-semibold">
                        {pluralize(recipientList.row_count, 'recipient')} in your list
                    </span>
                ) : (
                    <span className="text-warning">Couldn't load this list. Remove it and upload it again.</span>
                )}
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => removeRecipientList()}
                    data-attr="broadcast-recipient-list-remove"
                >
                    Remove list
                </LemonButton>
            </div>
            {recipientList ? (
                <div className="flex flex-wrap items-center gap-1 text-sm">
                    <span className="text-secondary">Use in the email:</span>
                    {recipientList.columns.map((column) => (
                        <LemonTag key={column}>{`{{ variables.${column} }}`}</LemonTag>
                    ))}
                </div>
            ) : null}
            {dropped.length > 0 ? (
                <span className="text-warning text-xs" data-attr="broadcast-recipient-list-dropped-rows">
                    Rows left out: {dropped.map(({ count, reason }) => `${count} ${reason}`).join(', ')}.
                </span>
            ) : null}
        </div>
    )
}
