import { BindLogic, useValues } from 'kea'

import { CyclotronJobInputType } from '~/types'

import { T3CodeMachineField } from './T3CodeMachineField'
import { t3CodeTaskSetupLogic } from './t3CodeTaskSetupLogic'
import { T3CodeTaskStatus } from './T3CodeTaskStatus'

export function T3CodeTaskSetup({
    actionId,
    inputs,
    setInputs,
}: {
    actionId: string
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
}): JSX.Element {
    const logicProps = {
        actionId,
        onWebhookUrl: (webhookUrl: string) => setInputs({ ...inputs, webhook_url: { value: webhookUrl } }),
    }
    const { createdWebhookUrl } = useValues(t3CodeTaskSetupLogic(logicProps))
    const hasWebhookUrl = Boolean(inputs.webhook_url?.value || inputs.webhook_url?.secret)

    return (
        <BindLogic logic={t3CodeTaskSetupLogic} props={logicProps}>
            <div className="flex flex-col gap-2 rounded border p-3 mb-2">
                <div>
                    <div className="font-semibold">Start new threads on a T3 Code machine</div>
                    <div className="text-secondary text-xs">
                        {hasWebhookUrl && !createdWebhookUrl
                            ? 'This step already sends its runs to a T3 Code task. Pick a machine and a project to send them to a new task instead.'
                            : 'Pick a machine and a project. PostHog creates a task there, and each run of this step starts a new thread in that project.'}
                    </div>
                </div>
                <T3CodeMachineField />
                <T3CodeTaskStatus />
            </div>
        </BindLogic>
    )
}
