import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

export const AiVisibilitySetupWizardFooter = ({
    onBack,
    backActions,
    children,
}: {
    onBack?: () => void
    backActions?: ReactNode
    children: ReactNode
}): JSX.Element => (
    <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t pt-4">
        <div className="flex flex-wrap items-center gap-2">
            {onBack ? (
                <LemonButton type="secondary" onClick={onBack} data-attr="ai-visibility-setup-back">
                    Back
                </LemonButton>
            ) : null}
            {backActions}
        </div>
        <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
)
