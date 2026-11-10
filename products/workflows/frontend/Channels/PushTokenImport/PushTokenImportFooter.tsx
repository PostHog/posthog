import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { pushTokenImportLogic } from './pushTokenImportLogic'

/** The buttons for the import dialog's current step: choosing a file, a running import, or a result. */
export function PushTokenImportFooter(): JSX.Element | null {
    const { loadingLatest, currentImport, isRunning, submitting, isStopping, startDisabledReason } =
        useValues(pushTokenImportLogic)
    const { closeImport, startImport, importUnknownPersons, stopImport, importAnotherFile } =
        useActions(pushTokenImportLogic)

    if (loadingLatest) {
        return null
    }
    if (isRunning) {
        return (
            <>
                <LemonButton type="secondary" onClick={closeImport}>
                    Close
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    onClick={stopImport}
                    disabledReason={isStopping ? 'Stopping the import' : null}
                    data-attr="push-token-import-stop"
                >
                    Stop import
                </LemonButton>
            </>
        )
    }
    if (currentImport) {
        return (
            <>
                <LemonButton type="secondary" onClick={importAnotherFile} data-attr="push-token-import-another-file">
                    Import another file
                </LemonButton>
                {currentImport.can_import_unknown_persons ? (
                    <LemonButton
                        type="secondary"
                        onClick={importUnknownPersons}
                        loading={submitting}
                        data-attr="push-token-import-create-persons"
                    >
                        Import anyway and create new persons
                    </LemonButton>
                ) : null}
                <LemonButton type="primary" onClick={closeImport}>
                    Done
                </LemonButton>
            </>
        )
    }
    return (
        <>
            <LemonButton
                type="secondary"
                onClick={closeImport}
                disabledReason={submitting ? 'Uploading the file' : null}
            >
                Cancel
            </LemonButton>
            <LemonButton
                type="primary"
                onClick={startImport}
                loading={submitting}
                disabledReason={submitting ? null : startDisabledReason}
                data-attr="push-token-import-start"
            >
                Import
            </LemonButton>
        </>
    )
}
