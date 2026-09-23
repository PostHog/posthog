import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { SetupInspectorDrawer } from './SetupInspectorDrawer'
import { setupInspectorLogic } from './setupInspectorLogic'

export function SetupInspectorButton(): JSX.Element | null {
    const { canInspect } = useValues(setupInspectorLogic)
    const { openSetupInspector } = useActions(setupInspectorLogic)

    if (!canInspect) {
        return null
    }
    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                onClick={openSetupInspector}
                tooltip="See what an agent reads about this project before it creates an experiment."
                data-attr="experiment-setup-context-open"
            >
                Setup context
            </LemonButton>
            <SetupInspectorDrawer />
        </>
    )
}
