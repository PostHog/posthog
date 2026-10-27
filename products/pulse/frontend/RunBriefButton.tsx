import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { BRIEF_ALREADY_GENERATING_MESSAGE, pulseLogic } from './pulseLogic'
import { QuillRunBriefButton } from './QuillRunBriefButton'

export function RunBriefButton(): JSX.Element {
    const { isGeneratingForSelectedConfig, generatedBriefLoading, selectedConfigId, dataProcessingAccepted } =
        useValues(pulseLogic)
    const { generateBrief } = useActions(pulseLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillRunBriefButton />
    }

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
