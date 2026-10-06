import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'

export function MakeItYoursEmailList({ templateId }: { templateId: string }): JSX.Element {
    const logic = firstRunMakeItYoursLogic({ templateId })
    const { templateEmails, openEmailId, editedEmailIds } = useValues(logic)
    const { openEmail } = useActions(logic)

    return (
        <div className="flex flex-col gap-1 rounded border bg-surface-primary p-2" data-attr="first-run-email-list">
            <span className="px-2 text-xs font-semibold uppercase text-secondary">
                {templateEmails.length} emails in this workflow
            </span>
            {templateEmails.map((email, index) => {
                const isOpen = email.id === openEmailId
                return (
                    <LemonButton
                        key={email.id}
                        fullWidth
                        active={isOpen}
                        onClick={() => openEmail(email.id)}
                        data-attr="first-run-email-list-item"
                        icon={<span className="w-5 text-center text-xs text-secondary">{index + 1}</span>}
                        sideIcon={
                            editedEmailIds.includes(email.id) ? (
                                <LemonTag type="success" size="small">
                                    Edited
                                </LemonTag>
                            ) : null
                        }
                    >
                        <span className="flex min-w-0 flex-col items-start text-left">
                            <span className="w-full truncate font-medium">{email.subject || 'No subject'}</span>
                            <span className="text-xs font-normal text-secondary">{email.timing}</span>
                        </span>
                    </LemonButton>
                )
            })}
        </div>
    )
}
