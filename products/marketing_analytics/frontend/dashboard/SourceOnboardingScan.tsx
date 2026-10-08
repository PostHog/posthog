import { LemonButton } from '@posthog/lemon-ui'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SourceSetupPanel } from './SourceSetupPanel'

export interface SourceOnboardingScanProps {
    loading: boolean
    failed: boolean
    suggestions: Suggestion[]
    onManual: () => void
    onContinue: () => void
    onRescan: () => void
    rescanLoading?: boolean
    rescanDisabledReason?: string | null
}

export function SourceOnboardingScan({
    loading,
    failed,
    suggestions,
    onManual,
    onContinue,
    onRescan,
    rescanLoading,
    rescanDisabledReason,
}: SourceOnboardingScanProps): JSX.Element {
    return (
        <SourceSetupPanel
            state={loading ? 'scanning' : failed ? 'error' : suggestions.length ? 'suggestions' : 'empty'}
            suggestions={suggestions}
            onRetry={onRescan}
            rescanLoading={rescanLoading}
            rescanDisabledReason={rescanDisabledReason}
            footer={
                <>
                    <LemonButton onClick={onManual} data-attr="marketing-onboarding-add-manually">
                        Skip and add manually
                    </LemonButton>
                    <LemonButton type="secondary" onClick={onContinue} data-attr="marketing-onboarding-continue">
                        Continue to dashboard
                    </LemonButton>
                </>
            }
        />
    )
}
