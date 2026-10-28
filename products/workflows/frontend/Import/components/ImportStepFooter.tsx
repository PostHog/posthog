import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { customerIOImportLogic } from '../customerIOImportLogic'

/** The Back button and the step's own actions, under each import step. */
export function ImportStepFooter({ children }: { children?: React.ReactNode }): JSX.Element {
    const { previousStep } = useActions(customerIOImportLogic)

    return (
        <div className="flex flex-wrap justify-between gap-2 border-t pt-3">
            <LemonButton type="secondary" onClick={previousStep} data-attr="messaging-import-back">
                Back
            </LemonButton>
            <div className="flex flex-wrap gap-2">{children}</div>
        </div>
    )
}
