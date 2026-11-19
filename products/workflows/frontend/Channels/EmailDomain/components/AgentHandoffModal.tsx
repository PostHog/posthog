import { useActions, useValues } from 'kea'

import { IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { emailDomainAgentLogic } from '../emailDomainAgentLogic'
import { emailDomainAutoConfigureLogic } from '../emailDomainAutoConfigureLogic'
import { emailDomainStatusLogic } from '../emailDomainStatusLogic'
import { HedgehogRobot } from '../hoggies'

function AgentSteps({
    host,
    recordCount,
    usesBrowser,
}: {
    host: string
    recordCount: number
    usesBrowser: boolean
}): JSX.Element {
    return (
        <ol className="list-decimal pl-5 text-sm text-secondary space-y-0.5">
            {usesBrowser ? (
                <>
                    <li>Opens {host} in a browser you are signed in to</li>
                    <li>Adds the {recordCount} records without touching anything else</li>
                    <li>Comes back here and clicks Check again until you are ready to send</li>
                </>
            ) : (
                <>
                    <li>Reads the records through the PostHog MCP tools</li>
                    <li>Adds them at {host} through its API, or hands you an approval link</li>
                    <li>Polls PostHog until you are ready to send</li>
                </>
            )}
        </ol>
    )
}

export function AgentHandoffModal(): JSX.Element {
    const { agentModalOpen, agentUsesBrowser, setupPrompt, claudeUrl } = useValues(emailDomainAgentLogic)
    const { closeAgentModal, setAgentUsesBrowser, copyPrompt, promptOpenedInClaude } = useActions(emailDomainAgentLogic)
    const { hostName } = useValues(emailDomainAutoConfigureLogic)
    const { records } = useValues(emailDomainStatusLogic)
    const host = hostName ?? 'your DNS host'

    return (
        <LemonModal
            isOpen={agentModalOpen}
            onClose={closeAgentModal}
            title="Let an agent add the settings"
            description="Your coding agent gets the exact records plus the checks it should run. You stay in control of the approval."
            width={640}
            footer={
                <div className="flex flex-wrap gap-2 justify-end">
                    <LemonButton
                        type="secondary"
                        icon={<IconCopy />}
                        onClick={copyPrompt}
                        data-attr="email-domain-copy-prompt"
                    >
                        Copy prompt
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconExternal />}
                        to={claudeUrl}
                        targetBlank
                        onClick={promptOpenedInClaude}
                        data-attr="email-domain-open-in-claude"
                    >
                        Open in Claude
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex gap-4 items-start">
                    <HedgehogRobot className="w-20 shrink-0" />
                    <LemonCheckbox
                        checked={agentUsesBrowser}
                        onChange={setAgentUsesBrowser}
                        label={`My agent can use a browser. Let it sign in to ${host} and add the records itself.`}
                    />
                </div>
                <AgentSteps host={host} recordCount={records.length} usesBrowser={agentUsesBrowser} />
                <pre className="text-xs whitespace-pre-wrap border rounded bg-fill-primary p-3 max-h-60 overflow-auto m-0">
                    {setupPrompt}
                </pre>
            </div>
        </LemonModal>
    )
}
