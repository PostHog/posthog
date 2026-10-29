import { useActions, useValues } from 'kea'

import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function NameStep(): JSX.Element {
    const { draft } = useValues(transactionalEmailWizardLogic)
    const { updateDraft } = useActions(transactionalEmailWizardLogic)

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonField.Pure label="Name" help="Only your team sees this.">
                <LemonInput
                    autoFocus
                    value={draft.name}
                    placeholder="Password reset"
                    onChange={(name) => updateDraft({ name })}
                    data-attr="transactional-email-wizard-name"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Description" showOptional>
                <LemonTextArea
                    value={draft.description}
                    placeholder="Sent when someone asks to reset their password"
                    onChange={(description) => updateDraft({ description })}
                    data-attr="transactional-email-wizard-description"
                />
            </LemonField.Pure>
            <LemonSwitch
                bordered
                checked={draft.sensitive}
                onChange={(sensitive) => updateDraft({ sensitive })}
                label={
                    <div>
                        <div className="font-semibold">Protect sensitive data</div>
                        <div className="text-secondary text-sm font-normal">
                            For emails with login codes or reset links. PostHog keeps no copy of what each email
                            contained, and doesn&apos;t track link clicks.
                        </div>
                    </div>
                }
                data-attr="transactional-email-wizard-sensitive"
            />
        </div>
    )
}
