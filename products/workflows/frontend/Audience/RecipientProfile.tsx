import { useActions } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { OpenPreferencesPageButton } from './OpenPreferencesPageButton'
import { recipientDetailLogic } from './recipientDetailLogic'
import { RecipientEmailActivity } from './RecipientEmailActivity'
import { RecipientPersonsCard } from './RecipientPersonsCard'
import { RecipientSuppressionBanner } from './RecipientSuppressionBanner'
import { RecipientTopicsCard } from './RecipientTopicsCard'

export function RecipientProfile({ recipient }: { recipient: RecipientApi }): JSX.Element {
    const { copyAddress } = useActions(recipientDetailLogic)
    return (
        <>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1 min-w-0">
                    <h2 className="m-0 text-xl font-semibold wrap-anywhere min-w-0" translate="no">
                        {recipient.email}
                    </h2>
                    <LemonButton
                        size="small"
                        icon={<IconCopy />}
                        onClick={copyAddress}
                        tooltip="Copy email address"
                        data-attr="audience-recipient-copy-email"
                    />
                </div>
                <OpenPreferencesPageButton />
            </div>
            {recipient.suppression && <RecipientSuppressionBanner suppression={recipient.suppression} />}
            <div className="flex flex-wrap gap-4">
                <RecipientTopicsCard recipient={recipient} />
                <RecipientPersonsCard recipient={recipient} />
            </div>
            <RecipientEmailActivity email={recipient.email} />
        </>
    )
}
