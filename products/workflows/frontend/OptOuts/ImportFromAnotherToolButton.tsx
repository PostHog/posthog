import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            {todayRailNav ? (
                <Button data-attr={dataAttr} onClick={() => openImportModal(null, entryPoint)} variant="outline">
                    {importButtonLabel}
                </Button>
            ) : (
                <LemonButton
                    data-attr={dataAttr}
                    onClick={() => openImportModal(null, entryPoint)}
                    type="secondary"
                    size="small"
                >
                    {importButtonLabel}
                </LemonButton>
            )}
        </AccessControlAction>
    )
}
