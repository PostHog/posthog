import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-command/WizardCommandBlock'

import { SendFromCodeSurface } from './firstCodeSendLogic'
import { ProjectSenderSnippet } from './ProjectSenderSnippet'

/** How to add the first send to a server: the Wizard command once it ships, and the snippet to do it by hand. */
export function SendFromCodeSetup({ surface }: { surface: SendFromCodeSurface }): JSX.Element {
    const wizardOffered = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD')
    const { isCloudOrDev } = useValues(preflightLogic)

    // The Wizard only reaches cloud and dev instances, so self-hosted keeps the snippet alone.
    if (!wizardOffered || !isCloudOrDev) {
        return <ProjectSenderSnippet surface={surface} />
    }
    return (
        <div className="flex flex-col gap-4">
            <WizardCommandBlock
                subcommand="transactional-email"
                description="The setup agent writes the email in your code, adds your project secret API key to your env file, and adds the first send to your server code."
            />
            <h4 className="m-0 text-sm font-semibold">Or add the send yourself</h4>
            <ProjectSenderSnippet surface={surface} />
        </div>
    )
}
