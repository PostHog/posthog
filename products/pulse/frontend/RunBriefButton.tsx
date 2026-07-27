import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { BRIEF_ALREADY_GENERATING_MESSAGE, pulseLogic } from './pulseLogic'

export function RunBriefButton(): JSX.Element {
    const { isGeneratingForSelectedConfig, generatedBriefLoading, selectedConfigId, dataProcessingAccepted } =
        useValues(pulseLogic)
    const { generateBrief } = useActions(pulseLogic)

    const disabledReason = !dataProcessingAccepted
        ? 'Approve AI data processing first'
        : isGeneratingForSelectedConfig && !generatedBriefLoading
          ? BRIEF_ALREADY_GENERATING_MESSAGE
          : undefined

    return (
        <LemonButton
            type="primary"
            loading={generatedBriefLoading}
            disabledReason={disabledReason}
            onClick={() => generateBrief({ configId: selectedConfigId })}
        >
            Run brief now
        </LemonButton>
    )
}
