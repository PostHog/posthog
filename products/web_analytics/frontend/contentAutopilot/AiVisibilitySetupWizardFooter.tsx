import { ReactNode } from 'react'

import { Button } from '@posthog/quill'

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
                <Button variant="outline" onClick={onBack} data-attr="ai-visibility-setup-back">
                    Back
                </Button>
            ) : null}
            {backActions}
        </div>
        <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
)
