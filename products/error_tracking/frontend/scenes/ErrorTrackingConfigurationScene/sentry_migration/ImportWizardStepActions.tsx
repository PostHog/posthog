import { ReactNode } from 'react'

import { Button } from '@posthog/quill'

export interface ImportWizardStepActionsProps {
    onBack: () => void
    children: ReactNode
}

export function ImportWizardStepActions({ onBack, children }: ImportWizardStepActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <Button variant="outline" onClick={onBack} data-attr="error-tracking-import-back">
                Back
            </Button>
            <div className="flex flex-wrap items-center gap-2">{children}</div>
        </div>
    )
}
