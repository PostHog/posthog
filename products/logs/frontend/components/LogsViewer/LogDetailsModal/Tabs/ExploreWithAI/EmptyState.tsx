import { IconAIText } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

export interface EmptyStateProps {
    onGenerate: () => void
    dataProcessingAccepted: boolean
    loading: boolean
}

export function EmptyState({ onGenerate, dataProcessingAccepted, loading }: EmptyStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-4 p-8">
            <IconAIText className="text-4xl text-muted" />
            <div className="text-center">
                <h4 className="font-semibold m-0">AI-powered incident analysis</h4>
                <p className="text-muted text-sm mt-1 mb-0">Get log analysis & prioritized actions.</p>
            </div>
            <AIConsentPopoverWrapper showArrow onApprove={onGenerate} hidden={loading}>
                <LemonButton
                    type="primary"
                    onClick={dataProcessingAccepted ? onGenerate : undefined}
                    loading={loading}
                    disabledReason={
                        !dataProcessingAccepted ? 'AI data processing must be approved to generate analysis' : undefined
                    }
                >
                    Analyze this log
                </LemonButton>
            </AIConsentPopoverWrapper>
        </div>
    )
}
