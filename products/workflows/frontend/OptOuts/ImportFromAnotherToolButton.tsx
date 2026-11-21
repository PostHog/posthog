import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { providerImportLogic } from './providerImportLogic'
import { ImportEntryPoint } from './providerImportOrder'

/** Opens the import window from a scene header. The scene renders the window itself. */
export function ImportFromAnotherToolButton({
    entryPoint,
    dataAttr,
}: {
    entryPoint: ImportEntryPoint
    dataAttr: string
}): JSX.Element {
    const { importButtonLabel } = useValues(providerImportLogic)
    const { openImportModal } = useActions(providerImportLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                data-attr={dataAttr}
                onClick={() => openImportModal(null, entryPoint)}
                type="secondary"
                size="small"
            >
                {importButtonLabel}
            </LemonButton>
        </AccessControlAction>
    )
}
