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
    const { setName, saveName } = useActions(broadcastWizardLogic)

    return (
        // Blur from the name field saves a draft's rename. Actions in the header blur other elements.
        <div onBlur={(e) => (e.target as HTMLElement).getAttribute('name') === 'name' && saveName()}>
            <SceneTitleSection
                name={name}
                description={null}
                resourceType={{ type: 'broadcasts' }}
                canEdit={canEdit}
                // Each keystroke lands in the wizard's state, so a click on Continue straight after typing saves the
                // new name. The blur save above reaches it a tick later.
                onNameChange={setName}
                renameDebounceMs={0}
                isLoading={broadcastLoading && !broadcast}
                nameSuffix={nameSuffix}
                actions={actions}
            />
        </div>
    )
}
