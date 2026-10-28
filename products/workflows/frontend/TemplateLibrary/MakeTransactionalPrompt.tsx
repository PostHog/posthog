import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateSceneLogicProps } from './messageTemplateSceneLogic'

export function MakeTransactionalPrompt(props: MessageTemplateSceneLogicProps): JSX.Element {
    const logic = messageTemplateLogic(props)
    const { template, templateChanged, isMakingTransactional } = useValues(logic)
    const { makeTransactional } = useActions(logic)

    const email = template.content.email
    const disabledReason = templateChanged
        ? 'Save your changes first'
        : !email?.subject
          ? 'Add a subject first'
          : !(email.html || email.text)
            ? 'Add a body first'
            : undefined

    return (
        <div className="flex flex-col gap-4 max-w-200" data-attr="make-transactional-prompt">
            <div>
                <h3 className="mb-1">Send this email from your code</h3>
                <p className="mb-0">
                    Make this template transactional to send it with one API call. Use it for emails a person triggers,
                    like password resets, receipts and sign-in codes.
                </p>
            </div>
            <ul className="list-disc pl-6 mb-0 flex flex-col gap-1">
                <li>Each send shows up here under Metrics and Sends, and on the recipient's person.</li>
                <li>
                    Your edits save as a draft. Publishing updates the live email, and each publish keeps a version.
                </li>
                <li>Transactional emails ignore marketing opt-outs, so don't use them for marketing.</li>
                <li>You can't undo this. The template stays transactional.</li>
            </ul>
            <div>
                <LemonButton
                    data-attr="make-message-template-transactional"
                    type="primary"
                    onClick={makeTransactional}
                    loading={isMakingTransactional}
                    disabledReason={disabledReason}
                >
                    Make transactional
                </LemonButton>
            </div>
        </div>
    )
}
