import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { ConversionActionsEditor } from './ConversionActionsEditor'
import { conversionActionsLogic } from './conversionActionsLogic'

export function ConversionActionsModal(): JSX.Element {
    const { editorOpen } = useValues(conversionActionsLogic)
    const { closeEditor } = useActions(conversionActionsLogic)
    return (
        <LemonModal isOpen={editorOpen} onClose={closeEditor} title="Conversion actions" width={560}>
            <ConversionActionsEditor />
        </LemonModal>
    )
}
