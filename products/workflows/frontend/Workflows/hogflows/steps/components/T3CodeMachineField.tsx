import { useActions, useValues } from 'kea'

import { LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { T3CodeProjectField } from './T3CodeProjectField'
import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'

export function T3CodeMachineField(): JSX.Element | null {
    const { machines, machinesLoading, machine, selectionDisabledReason } = useValues(t3CodeTaskSetupLogic)
    const { setMachine, loadMachines } = useActions(t3CodeTaskSetupLogic)

    if (machines === null) {
        return machinesLoading ? <Spinner /> : null
    }
    if (machines.length === 0) {
        return (
            <div className="text-xs">
                No T3 Code machine is connected. In T3 Code, copy the machine's MCP URL from Settings &gt; Environments.
                Add it in <Link to={urls.settings('mcp-servers')}>MCP servers settings</Link> and approve the sign-in
                with Supervised access or more.{' '}
                <Link onClick={() => loadMachines()} data-attr="workflow-t3-code-reload-machines">
                    Check again
                </Link>
            </div>
        )
    }
    return (
        <>
            <LemonField.Pure label="Machine">
                <LemonSelect<string | null>
                    fullWidth
                    value={machine}
                    onChange={setMachine}
                    options={machines.map(({ host, name }) => ({ label: name, value: host }))}
                    placeholder="Choose a machine"
                    disabledReason={selectionDisabledReason ?? undefined}
                    data-attr="workflow-t3-code-machine"
                />
            </LemonField.Pure>
            {machine && <T3CodeProjectField />}
        </>
    )
}
