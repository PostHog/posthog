import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'

export function QuillCreateScannerButton({
    acceptedLabel,
    dataAttr,
}: {
    acceptedLabel: string
    dataAttr: string
}): JSX.Element {
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(aiConsentLogic)
    const { push } = useActions(router)
    const [consentRequested, setConsentRequested] = useState(false)
    const goToCreate = (): void => push(urls.replayVisionNewScanner())

    const canApproveConsent = !dataProcessingApprovalDisabledReason
    const label = dataProcessingAccepted
        ? acceptedLabel
        : canApproveConsent
          ? 'Allow AI analysis and create scanner'
          : 'Ask an admin to enable AI analysis'

    const button = (
        <Button
            variant="primary"
            disabledReason={getReplayVisionEditDisabledReason()}
            data-attr={dataAttr}
            onClick={() => (dataProcessingAccepted ? goToCreate() : setConsentRequested(true))}
        >
            {(dataProcessingAccepted || canApproveConsent) && <IconPlus />}
            {label}
        </Button>
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
            pendingRedirectUrl={urls.replayVisionNewScanner()}
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
