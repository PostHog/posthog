import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'

export interface SuggestionActionRowProps extends TurnSuggestionLogicProps {
    label: string
    failedMessage: ReactNode
    dataAttr: string
}

/** The tail every card shares: the failure banner and the one button that takes the offer. */
export function SuggestionActionRow({
    label,
    failedMessage,
    dataAttr,
    ...logicProps
}: SuggestionActionRowProps): JSX.Element {
    const logic = suggestionActionLogic(logicProps)
    const { acceptedLoading, acceptDisabledReason, acceptFailed } = useValues(logic)
    const { accept } = useActions(logic)

    return (
        <>
            {acceptFailed && <LemonBanner type="error">{failedMessage}</LemonBanner>}
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={accept}
                    loading={acceptedLoading}
                    disabledReason={acceptDisabledReason ?? undefined}
                    data-attr={dataAttr}
                >
                    {label}
                </LemonButton>
            </div>
        </>
    )
}
