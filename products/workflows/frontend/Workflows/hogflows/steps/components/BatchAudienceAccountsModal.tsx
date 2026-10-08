import { LemonModal } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AccountsQuery } from '~/queries/schema/schema-general'

import { AccountAudienceTable } from 'products/customer_analytics/frontend/components/AccountAudienceTable/AccountAudienceTable'

export interface BatchAudienceAccountsModalProps {
    actionId: string
    audienceQuery: AccountsQuery
    affected: number
    isOpen: boolean
    onClose: () => void
}

export function BatchAudienceAccountsModal({
    actionId,
    audienceQuery,
    affected,
    isOpen,
    onClose,
}: BatchAudienceAccountsModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width="90vw"
            maxWidth={1400}
            title="Accounts in this batch"
            description={`About ${humanFriendlyNumber(affected)} ${affected === 1 ? 'account matches' : 'accounts match'} this trigger. Filters and columns here only change this list, not the workflow.`}
        >
            {/* Unmounting on close resets the table's filters and columns for the next open. */}
            {isOpen && (
                <AccountAudienceTable
                    scope={`workflow-batch-audience-${actionId}`}
                    audienceQuery={audienceQuery}
                    source="workflow_batch_audience"
                />
            )}
        </LemonModal>
    )
}
