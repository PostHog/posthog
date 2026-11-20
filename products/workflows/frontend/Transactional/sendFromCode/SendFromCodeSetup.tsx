import { useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-command/WizardCommandBlock'

import { SendFromCodeSurface } from './firstCodeSendLogic'
import { SendFromCodeAgentPrompt } from './SendFromCodeAgentPrompt'
import { SendFromCodeSnippet } from './SendFromCodeSnippet'
import { sendingDomainLogic } from './sendingDomainLogic'

export function SendFromCodeSetup({ surface }: { surface: SendFromCodeSurface }): JSX.Element {
    const wizardOffered = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD')
    const { isCloudOrDev } = useValues(preflightLogic)
    const { sendingDomain, integrationsFailed } = useValues(sendingDomainLogic)
    const [codeShown, setCodeShown] = useState(false)
    const codeId = useId()
    const domainLoading = !sendingDomain && !integrationsFailed
    const from = sendingDomain?.status === 'verified' ? sendingDomain.from : null

    return (
        <div className="flex flex-col gap-4">
            {wizardOffered && isCloudOrDev ? (
                <>
                    <WizardCommandBlock
                        // pinned: the Wizard's CLI word. The copy event records it as `command`, so copies count per released command
                        subcommand="email"
                        description="The setup agent writes the email in your code, adds your project secret API key to your env file, and adds the first send to your server code."
                    />
                    <h4 className="m-0 text-sm font-semibold">Or use your own coding agent</h4>
                </>
            ) : null}
            {domainLoading ? (
                <LemonSkeleton className="h-24" />
            ) : (
                <>
                    <SendFromCodeAgentPrompt from={from} surface={surface} />
                    <div className="flex flex-col gap-2 border-t pt-3">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            className="self-start"
                            icon={codeShown ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={() => setCodeShown(!codeShown)}
                            aria-expanded={codeShown}
                            aria-controls={codeId}
                            data-attr="send-from-code-show-code"
                        >
                            {codeShown ? 'Hide the code' : 'Write the code yourself'}
                        </LemonButton>
                        {codeShown ? (
                            <div id={codeId} className="flex flex-col gap-2">
                                <p className="m-0 text-sm text-secondary">
                                    Writing it by hand? Here's everything the send needs.
                                </p>
                                <SendFromCodeSnippet from={from} surface={surface} />
                            </div>
                        ) : null}
                    </div>
                </>
            )}
        </div>
    )
}
