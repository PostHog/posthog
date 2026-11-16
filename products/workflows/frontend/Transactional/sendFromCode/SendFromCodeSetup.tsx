import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-command/WizardCommandBlock'

import { SendFromCodeSurface } from './firstCodeSendLogic'
import { SendFromCodeSnippet } from './SendFromCodeSnippet'
import { sendingDomainLogic } from './sendingDomainLogic'

export function SendFromCodeSetup({ surface }: { surface: SendFromCodeSurface }): JSX.Element {
    const wizardOffered = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD')
    const { isCloudOrDev } = useValues(preflightLogic)
    const { sendingDomain, integrationsFailed } = useValues(sendingDomainLogic)

    const snippet =
        !sendingDomain && !integrationsFailed ? (
            <LemonSkeleton className="h-60" />
        ) : (
            <SendFromCodeSnippet
                from={sendingDomain?.status === 'verified' ? sendingDomain.from : null}
                surface={surface}
            />
        )
    if (!wizardOffered || !isCloudOrDev) {
        return snippet
    }
    return (
        <div className="flex flex-col gap-4">
            <WizardCommandBlock
                subcommand="transactional-email"
                description="The setup agent writes the email in your code, adds your project secret API key to your env file, and adds the first send to your server code."
            />
            <h4 className="m-0 text-sm font-semibold">Or add the send yourself</h4>
            {snippet}
        </div>
    )
}
