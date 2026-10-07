import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { TestSendOutcome, firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'

export function MakeItYoursActions({ templateId }: { templateId: string }): JSX.Element {
    const logic = firstRunMakeItYoursLogic({ templateId })
    const {
        firstRunSender,
        firstRunSenderLoading,
        enableWorkflow,
        enableDisabledReason,
        sendTestDisabledReason,
        createDisabledReason,
        testSendOutcome,
        testSendResultLoading,
        createdWorkflowLoading,
        createError,
    } = useValues(logic)
    const { sendTest, createWorkflow, setEnableWorkflow } = useActions(logic)

    return (
        <div className="flex flex-col gap-3" data-attr="first-run-actions">
            {!firstRunSender && !firstRunSenderLoading && (
                <LemonBanner type="info">
                    No email sender is set up yet. Connect one in <Link to={urls.workflows('channels')}>Channels</Link>{' '}
                    to send a test or enable the workflow.
                </LemonBanner>
            )}
            {testSendOutcome && <TestSendOutcomeBanner outcome={testSendOutcome} />}
            <LemonButton
                type="secondary"
                center
                fullWidth
                onClick={() => sendTest()}
                loading={testSendResultLoading}
                disabledReason={sendTestDisabledReason}
                data-attr="first-run-send-test"
            >
                {testSendOutcome?.kind === 'sent' ? 'Send another test' : 'Send me a test'}
            </LemonButton>
            {createError && (
                <LemonBanner type="error" data-attr="first-run-create-error">
                    Couldn't create the workflow: {createError}
                </LemonBanner>
            )}
            <LemonButton
                type="primary"
                size="large"
                center
                fullWidth
                onClick={() => createWorkflow()}
                loading={createdWorkflowLoading}
                disabledReason={createDisabledReason}
                data-attr="first-run-create-workflow"
            >
                {enableWorkflow ? 'Enable and open workflow' : 'Open workflow'}
            </LemonButton>
            <LemonSwitch
                checked={enableWorkflow}
                onChange={setEnableWorkflow}
                disabledReason={enableDisabledReason}
                label="Enable workflow"
                bordered
                fullWidth
                data-attr="first-run-enable-switch"
            />
            <span className="text-xs text-secondary">{enableHelp(enableWorkflow, firstRunSender?.display_name)}</span>
        </div>
    )
}

function enableHelp(enableWorkflow: boolean, senderName: string | undefined): string {
    if (enableWorkflow && senderName) {
        return `It starts sending right away, from ${senderName}.`
    }
    if (senderName) {
        return `It opens as a draft and sends nothing until you enable it. Then it sends from ${senderName}.`
    }
    return 'It opens as a draft and sends nothing until you enable it.'
}

function TestSendOutcomeBanner({ outcome }: { outcome: TestSendOutcome }): JSX.Element {
    if (outcome.kind === 'sent') {
        return (
            <LemonBanner type="success" data-attr="first-run-test-sent">
                Test sent to {outcome.recipient}. Check your inbox.
            </LemonBanner>
        )
    }
    if (outcome.kind === 'skipped') {
        return (
            <LemonBanner type="warning" data-attr="first-run-test-skipped">
                Nothing was sent. {outcome.reason}
            </LemonBanner>
        )
    }
    return (
        <LemonBanner type="error" data-attr="first-run-test-failed">
            Couldn't send the test email. Try again.
        </LemonBanner>
    )
}
