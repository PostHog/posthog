import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { senderFrom } from 'scenes/hog-functions/email-templater/emailSenderFields'

import { TransactionalEmailApiExample } from '../../../TemplateLibrary/TransactionalEmailApiExample'
import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function SendStep(): JSX.Element {
    const { draft, senders, variables } = useValues(transactionalEmailWizardLogic)
    const from = senderFrom(draft.email)
    const sender = senders.find((candidate) => candidate.id === from.integrationId)

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <dl className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-1 m-0 border rounded p-3">
                <dt className="text-secondary">Name</dt>
                <dd className="m-0 flex gap-2 items-center flex-wrap">
                    {draft.name}
                    {draft.sensitive ? <LemonTag type="highlight">Sensitive</LemonTag> : null}
                </dd>
                <dt className="text-secondary">From</dt>
                <dd className="m-0 truncate">{from.email || sender?.config?.email}</dd>
                <dt className="text-secondary">Subject</dt>
                <dd className="m-0 truncate">{draft.email.subject}</dd>
                <dt className="text-secondary">Variables</dt>
                <dd className="m-0 flex gap-1 flex-wrap">
                    {variables.length ? variables.map((name) => <code key={name}>{name}</code>) : 'None'}
                </dd>
            </dl>
            <TransactionalEmailApiExample templateId="TEMPLATE_ID" variables={variables} />
            <ul className="list-disc pl-6 m-0 flex flex-col gap-1 text-secondary">
                <li>
                    <code>TEMPLATE_ID</code> is filled in on the email's page once you create it.
                </li>
                <li>Transactional emails ignore marketing opt-outs, so don't use them for marketing.</li>
                <li>Later edits save as a draft until you publish them.</li>
                <li>An email created here stays transactional.</li>
            </ul>
        </div>
    )
}
