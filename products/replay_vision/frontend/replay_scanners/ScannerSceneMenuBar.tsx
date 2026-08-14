import { useActions, useValues } from 'kea'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneMenuBar, SceneMenuBarPopover } from '~/layout/scenes/components/SceneMenuBar'

import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { SCANNER_RESOURCE_TYPE } from './constants'
import { replayScannerLogic } from './replayScannerLogic'

/** Flag-on counterpart to the scanner editor's ScenePanel. Both surfaces must carry the same items. */
export function ScannerSceneMenuBar({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <ScannerSceneMenuBarInner scannerId={scannerId} />
}

function ScannerSceneMenuBarInner({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner, availableObjectTags } = useValues(replayScannerLogic({ id: scannerId }))
    const { setScannerValue } = useActions(replayScannerLogic({ id: scannerId }))

    return (
        <SceneMenuBar>
            <SceneMenuBarPopover label="Metadata" dataAttr={`${SCANNER_RESOURCE_TYPE}-menubar-metadata`}>
                <SceneTagsCombobox
                    onSave={(tags) => setScannerValue('tags', tags)}
                    tags={scanner?.tags ?? []}
                    tagsAvailable={availableObjectTags}
                    canEdit={!getReplayVisionEditDisabledReason(scanner?.user_access_level)}
                    dataAttrKey={SCANNER_RESOURCE_TYPE}
                />
            </SceneMenuBarPopover>
        </SceneMenuBar>
    )
}
