import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'

/**
 * "Create scanner" CTA that requires the organization to have approved AI data processing first.
 * When consent is missing, clicking surfaces the AI consent popover; approving flows straight into
 * the create-scanner journey, so the empty state stays the same whether or not consent is set.
 */
export function CreateScannerButton({
    acceptedLabel,
    dataAttr,
    size = 'small',
}: {
    acceptedLabel: string
    dataAttr: string
    size?: 'small' | 'medium'
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { push } = useActions(router)
    const [consentRequested, setConsentRequested] = useState(false)
    const goToCreate = (): void => push(urls.replayVisionTemplates())

    const button = (
        <LemonButton
            type="primary"
            size={size}
            icon={<IconPlus />}
            disabledReason={getReplayVisionEditDisabledReason()}
            data-attr={dataAttr}
            onClick={() => (dataProcessingAccepted ? goToCreate() : setConsentRequested(true))}
        >
            {dataProcessingAccepted ? acceptedLabel : 'Allow AI analysis and create scanner'}
        </LemonButton>
    )

    if (dataProcessingAccepted) {
        return button
    }

    return (
        <AIConsentPopoverWrapper
            placement="bottom-end"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            pendingRedirectUrl={urls.replayVisionTemplates()}
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                goToCreate()
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
    )
}
