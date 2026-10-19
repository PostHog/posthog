import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { SetupInspectorDrawer } from './SetupInspectorDrawer'
import { setupInspectorLogic } from './setupInspectorLogic'

export function QuillSetupInspectorButton(): JSX.Element | null {
    const { canInspect } = useValues(setupInspectorLogic)
    const { openSetupInspector } = useActions(setupInspectorLogic)

    if (!canInspect) {
        return null
    }
    return (
        <>
            <Button
                variant="outline"
                onClick={openSetupInspector}
                tooltip="See what an agent reads about this project before it creates an experiment."
                data-attr="experiment-setup-context-open"
            >
                Setup context
            </Button>
            <SetupInspectorDrawer />
        </>
    )
}
