import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

export interface ImportWizardStepActionsProps {
    onBack: () => void
    children: ReactNode
}

export function ImportWizardStepActions({ onBack, children }: ImportWizardStepActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <LemonButton type="secondary" onClick={onBack} data-attr="error-tracking-import-back">
                Back
            </LemonButton>
            <div className="flex flex-wrap items-center gap-2">{children}</div>
        </div>
    )
}
