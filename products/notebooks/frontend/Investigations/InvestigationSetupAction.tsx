import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NewInvestigationButton } from './NewInvestigationButton'

export function InvestigationSetupAction(): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Notebook}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <NewInvestigationButton />
        </AccessControlAction>
    )
}
