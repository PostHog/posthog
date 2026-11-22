import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { providerImportLogic } from './providerImportLogic'
import { ImportEntryPoint } from './providerImportOrder'

/** The empty-state line that opens the import window. The scene renders the window itself. */
export function ImportFromAnotherToolPrompt({
    entryPoint,
    linkText,
    dataAttr,
}: {
    entryPoint: ImportEntryPoint
    linkText: string
    dataAttr: string
}): JSX.Element | null {
    const { openImportModal } = useActions(providerImportLogic)
    if (getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor)) {
        return null
    }
    return (
        <p className="m-0 text-center text-secondary text-sm">
            Moving from another tool?{' '}
            <Link onClick={() => openImportModal(null, entryPoint)} data-attr={dataAttr}>
                {linkText}
            </Link>
        </p>
    )
}
