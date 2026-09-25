import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LogsSourceWizardStep, logsSourcesLogic } from './logsSourcesLogic'
import { ConnectStep } from './steps/ConnectStep'
import { DetailsStep } from './steps/DetailsStep'
import { WaitingStep } from './steps/WaitingStep'

export function LogsSourceWizard(): JSX.Element {
    const { wizardOpen, wizardStep, wizardSource, canCreate, createPending, wizardSourceIsReceiving } =
        useValues(logsSourcesLogic)
    const { closeWizard, createSource, setWizardStep } = useActions(logsSourcesLogic)
    const sourceName = wizardSource?.name ?? 'this source'

    const steps: Record<LogsSourceWizardStep, { title: string; body: JSX.Element; footer: JSX.Element }> = {
        details: {
            title: 'Add a CloudWatch source',
            body: <DetailsStep />,
            footer: (
                <>
                    <LemonButton type="secondary" onClick={closeWizard}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createSource}
                        loading={createPending}
                        disabledReason={canCreate ? undefined : 'Enter a name for the source'}
                        data-attr="logs-source-create"
                    >
                        Create source
                    </LemonButton>
                </>
            ),
        },
        connect: {
            title: `Connect Firehose to ${sourceName}`,
            body: <ConnectStep />,
            footer: (
                <>
                    <LemonButton type="secondary" onClick={closeWizard}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => setWizardStep('waiting')}
                        data-attr="logs-source-wizard-continue"
                    >
                        I have set up Firehose
                    </LemonButton>
                </>
            ),
        },
        waiting: {
            title: `Waiting for ${sourceName}`,
            body: <WaitingStep />,
            footer: (
                <>
                    <LemonButton type="secondary" onClick={() => setWizardStep('connect')}>
                        Back to setup values
                    </LemonButton>
                    <LemonButton type="primary" onClick={closeWizard} data-attr="logs-source-wizard-done">
                        {wizardSourceIsReceiving ? 'Done' : 'Close'}
                    </LemonButton>
                </>
            ),
        },
    }
    const step = steps[wizardStep]

    return (
        <LemonModal isOpen={wizardOpen} onClose={closeWizard} title={step.title} footer={step.footer} width={640}>
            {step.body}
        </LemonModal>
    )
}
