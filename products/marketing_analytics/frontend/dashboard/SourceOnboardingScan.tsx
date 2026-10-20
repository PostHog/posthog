import { LemonButton } from '@posthog/lemon-ui'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SourceSetupPanel } from './SourceSetupPanel'

export interface SourceOnboardingScanProps {
    dismissed?: boolean
    onRestore?: () => void
    loading: boolean
    failed: boolean
    suggestions: Suggestion[]
    onManual: () => void
    onContinue: () => void
    onRescan: () => void
    rescanLoading?: boolean
    rescanDisabledReason?: string | null
    headerAction?: ReactNode
}

export function SourceOnboardingScan({
    dismissed,
    onRestore,
    loading,
    failed,
    suggestions,
    onManual,
    onContinue,
    onRescan,
    rescanLoading,
    rescanDisabledReason,
    headerAction,
}: SourceOnboardingScanProps): JSX.Element {
    return (
        <SourceSetupPanel
            headerAction={headerAction}
            state={
                loading
                    ? 'scanning'
                    : failed
                      ? 'error'
                      : suggestions.length
                        ? 'suggestions'
                        : dismissed
                          ? 'dismissed'
                          : 'empty'
            }
            suggestions={suggestions}
            onRestore={onRestore}
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
import type { ReactNode } from 'react'
