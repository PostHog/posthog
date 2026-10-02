import { BindLogic, useActions, useValues } from 'kea'

import { IconArrowLeft, IconCopy, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { recipientDetailLogic } from './recipientDetailLogic'
import { RecipientEmailActivity } from './RecipientEmailActivity'
import { RecipientPersonsCard } from './RecipientPersonsCard'
import { RecipientSuppressionBanner } from './RecipientSuppressionBanner'
import { RecipientTopicsCard } from './RecipientTopicsCard'

function OpenPreferencesPageButton(): JSX.Element {
    const { preferencesUrlLoading } = useValues(recipientDetailLogic)
    const { openPreferencesPage } = useActions(recipientDetailLogic)
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconExternal />}
            loading={preferencesUrlLoading}
            onClick={openPreferencesPage}
            tooltip="Opens the page where this recipient manages their topics, in a new tab"
            data-attr="audience-recipient-preferences-page"
        >
            Open preferences page
        </LemonButton>
    )
}

function RecipientProfile({ recipient }: { recipient: RecipientApi }): JSX.Element {
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
                        onClick={() => void copyToClipboard(recipient.email, 'email address')}
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
