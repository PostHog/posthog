import { useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { organizationLogic } from 'scenes/organizationLogic'

import { ImportWizard } from './ImportWizard'

export function ImportScene(): JSX.Element {
    const { isAdminOrOwner } = useValues(organizationLogic)

    if (isAdminOrOwner === false) {
        return <AccessDenied object="imports" inline />
    }
    return <ImportWizard />
}
