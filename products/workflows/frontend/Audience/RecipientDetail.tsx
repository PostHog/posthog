import { BindLogic, useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { urls } from 'scenes/urls'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { recipientDetailLogic } from './recipientDetailLogic'
import { RecipientEmailActivity } from './RecipientEmailActivity'
import { RecipientPersonsCard } from './RecipientPersonsCard'
import { RecipientSuppressionBanner } from './RecipientSuppressionBanner'
import { RecipientTopicsCard } from './RecipientTopicsCard'

function RecipientProfile({ recipient }: { recipient: RecipientApi }): JSX.Element {
    return (
        <>
            <h2 className="m-0 text-xl font-semibold wrap-anywhere">
                <CopyToClipboardInline explicitValue={recipient.email} description="email address">
                    <span translate="no">{recipient.email}</span>
                </CopyToClipboardInline>
            </h2>
            {recipient.suppression && <RecipientSuppressionBanner suppression={recipient.suppression} />}
            <div className="flex flex-wrap gap-4">
                <RecipientTopicsCard recipient={recipient} />
                <RecipientPersonsCard recipient={recipient} />
            </div>
            <RecipientEmailActivity email={recipient.email} />
        </>
    )
}

function RecipientDetailBody(): JSX.Element {
    const { recipientView } = useValues(recipientDetailLogic)
    const { loadRecipient } = useActions(recipientDetailLogic)

    switch (recipientView.state) {
        case 'loading':
            return <LemonSkeleton className="h-64" />
        case 'error':
            return (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadRecipient, 'data-attr': 'audience-recipient-retry' }}
                >
                    Couldn't load this recipient. Try again in a moment.
                </LemonBanner>
            )
        case 'not-found':
            return (
                <EmptyMessage
                    title="No recipient with this address"
                    description="PostHog has no preference, suppression or person for this address. Check the spelling, or find it in the list."
                    buttonText="Back to recipients"
                    buttonTo={urls.audience()}
                    buttonDataAttr="audience-recipient-not-found-back"
                />
            )
        case 'found':
            return <RecipientProfile recipient={recipientView.recipient} />
    }
}

export function RecipientDetail({ email }: { email: string }): JSX.Element {
    return (
        <BindLogic logic={recipientDetailLogic} props={{ email }}>
            <div className="flex flex-col gap-4 min-w-0" data-attr="audience-recipient-detail">
                <div>
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.audience()}>
                        Recipients
                    </LemonButton>
                </div>
                <RecipientDetailBody />
            </div>
        </BindLogic>
    )
}
