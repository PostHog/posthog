import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { EmailTemplater } from 'scenes/hog-functions/email-templater/EmailTemplater'

import { variablePlaceholder } from '../emailVariables'
import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function ContentStep(): JSX.Element {
    const { draft, variables } = useValues(transactionalEmailWizardLogic)
    const { updateDraft } = useActions(transactionalEmailWizardLogic)
    const [newVariable, setNewVariable] = useState('')
    const newVariableName = newVariable.trim().replace(/[^A-Za-z0-9_]/g, '_')

    return (
        <div className="flex flex-col @min-[64rem]/main-content:flex-row gap-4 min-h-[36rem]">
            <div className="flex flex-col flex-1 min-w-0">
                <EmailTemplater
                    value={draft.email}
                    onChange={(email) => updateDraft({ email })}
                    type="native_email_transactional_template"
                    layout="inline"
                />
            </div>
            <div
                className="flex flex-col gap-2 @min-[64rem]/main-content:w-64 shrink-0 border rounded p-3 self-start"
                data-attr="transactional-email-wizard-variables"
            >
                <div className="font-semibold">Variables your code sends</div>
                {variables.length ? (
                    <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                        {variables.map((name) => (
                            <li key={name}>
                                <code>{name}</code>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="text-secondary text-sm m-0">This email doesn't use any variables yet.</p>
                )}
                <p className="text-secondary text-sm m-0">
                    The list comes from the email: every <code>{'{{ variables.… }}'}</code> in the subject or body. Your
                    code fills them through <code>message_data</code>. Person properties aren't available.
                </p>
                <div className="flex gap-1">
                    <LemonInput
                        size="small"
                        className="flex-1 min-w-0"
                        placeholder="reset_link"
                        value={newVariable}
                        onChange={setNewVariable}
                        data-attr="transactional-email-wizard-new-variable"
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconCopy />}
                        disabledReason={!newVariableName ? 'Name the variable first' : undefined}
                        onClick={() => {
                            void copyToClipboard(variablePlaceholder(newVariableName), 'placeholder')
                            setNewVariable('')
                        }}
                        tooltip="Copies the placeholder. Paste it into the email."
                    >
                        Copy
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
