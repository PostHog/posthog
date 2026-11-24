import { Button } from '@posthog/quill'

import type { ImportWizardStepActionsProps } from './ImportWizardStepActions'

export function QuillImportWizardStepActions({ onBack, children }: ImportWizardStepActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <Button variant="outline" onClick={onBack} data-attr="error-tracking-import-back">
                Back
            </Button>
            <div className="flex flex-wrap items-center gap-2">{children}</div>
        </div>
    )
}
