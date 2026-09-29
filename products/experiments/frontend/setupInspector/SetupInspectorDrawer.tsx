import { useActions, useValues } from 'kea'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonDrawer } from 'lib/lemon-ui/LemonDrawer/LemonDrawer'

import { SetupInspectorForm } from './SetupInspectorForm'
import { setupInspectorLogic } from './setupInspectorLogic'
import { SetupInspectorResults } from './SetupInspectorResults'

export function SetupInspectorDrawer(): JSX.Element {
    const { isOpen } = useValues(setupInspectorLogic)
    const { closeSetupInspector } = useActions(setupInspectorLogic)

    return (
        <LemonDrawer
            isOpen={isOpen}
            onClose={closeSetupInspector}
            width="80vw"
            resizable
            title="Experiment setup context"
            description="The facts the experiment-setup-context tool gives an agent before it creates an experiment in this project."
            data-attr="experiment-setup-context-drawer"
        >
            <div className="@container/drawer flex flex-col gap-4">
                <SetupInspectorForm />
                <LemonDivider className="my-0" />
                <SetupInspectorResults />
            </div>
        </LemonDrawer>
    )
}
