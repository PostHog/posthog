import { useActions, useValues } from 'kea'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { broadcastWizardLogic } from './broadcastWizardLogic'

export interface BroadcastSceneHeaderProps {
    /** Only a draft is renamed in place; a live broadcast shows its name read-only. */
    canEdit?: boolean
    nameSuffix?: React.ReactNode
    actions?: JSX.Element
}

/** The broadcast wizard and summary header, shaped like the workflow editor's. */
export function BroadcastSceneHeader({ canEdit = false, nameSuffix, actions }: BroadcastSceneHeaderProps): JSX.Element {
    const { name, broadcast, broadcastLoading } = useValues(broadcastWizardLogic)
    const { setName } = useActions(broadcastWizardLogic)

    return (
        <SceneTitleSection
            name={name}
            description={null}
            resourceType={{ type: 'broadcasts' }}
            canEdit={canEdit}
            onNameChange={setName}
            saveOnBlur
            renameDebounceMs={0}
            isLoading={broadcastLoading && !broadcast}
            nameSuffix={nameSuffix}
            actions={actions}
        />
    )
}
