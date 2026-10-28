import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'

import { cleanVariableName } from '../emailVariables'
import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function ContentStep(): JSX.Element {
    const { draft, variables, panelVariables, editorGlobals } = useValues(transactionalEmailWizardLogic)
    const { updateDraft, addVariable } = useActions(transactionalEmailWizardLogic)
    const [newVariable, setNewVariable] = useState('')
    const [templatePickerOpen, setTemplatePickerOpen] = useState(false)
    const newVariableName = cleanVariableName(newVariable)
    const submitNewVariable = (): void => {
        if (newVariableName) {
            addVariable(newVariableName)
            setNewVariable('')
        }
    }

    return (
        <div className="flex flex-col @min-[64rem]/main-content:flex-row gap-4 min-h-[36rem]">
            <div className="flex flex-col flex-1 min-w-0 gap-2">
                <div className="flex justify-end">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setTemplatePickerOpen(true)}
                        data-attr="transactional-email-wizard-template-picker"
                    >
                        Start from template
                    </LemonButton>
                </div>
                <EmailTemplater
                    value={draft.email}
                    onChange={(email) => updateDraft({ email })}
                    type="native_email_transactional_template"
                    variables={editorGlobals}
                    layout="inline"
                />
                {/* The picker reads the unkeyed templater logic, so it renders after the editor to mount that logic with the editor's props. */}
                <TemplatePickerModal isOpen={templatePickerOpen} onClose={() => setTemplatePickerOpen(false)} />
            </div>
            <div
                className="flex flex-col gap-2 @min-[64rem]/main-content:w-64 shrink-0 border rounded p-3 self-start"
                data-attr="transactional-email-wizard-variables"
            >
                <div className="font-semibold">Variables your code sends</div>
                <p className="text-secondary text-sm m-0">
                    Your code passes these in <code>message_data</code> with each send. Person properties aren't
                    available.
                </p>
                {panelVariables.length ? (
                    <ul className="flex flex-col gap-1 m-0 p-0 list-none">
                        {panelVariables.map((name) => (
                            <li key={name} className="flex items-center justify-between gap-2">
                                <code className="truncate">{name}</code>
                                {variables.includes(name) ? null : <LemonTag size="small">Not used yet</LemonTag>}
                            </li>
                        ))}
                    </ul>
                ) : null}
                <div className="flex gap-1">
                    <LemonInput
                        size="small"
                        className="flex-1 min-w-0"
                        placeholder="Variable name, like first_name"
                        value={newVariable}
                        onChange={setNewVariable}
                        onPressEnter={submitNewVariable}
                        data-attr="transactional-email-wizard-new-variable"
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPlus />}
                        disabledReason={!newVariableName ? 'Type a variable name first' : undefined}
                        onClick={submitNewVariable}
                        data-attr="transactional-email-wizard-add-variable"
                    >
                        Add
                    </LemonButton>
                </div>
                <p className="text-secondary text-sm m-0">
                    Insert one in the body from <b>Merge tags</b> in a text block's toolbar. In the subject, type it as{' '}
                    <code>{'{{ variables.first_name }}'}</code>.
                </p>
            </div>
        </div>
    )
}
