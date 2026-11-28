import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonCard, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'

export function NameStep(): JSX.Element {
    const { draft } = useValues(transactionalEmailWizardLogic)
    const { updateDraft } = useActions(transactionalEmailWizardLogic)
    const sensitiveSwitchId = useId()
    const clickTrackingSwitchId = useId()

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
            <LemonCard hoverEffect={false} className="p-4">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0">
                        <IconLock className="text-xl text-secondary shrink-0 mt-0.5" />
                        <div className="min-w-0">
                            <label htmlFor={sensitiveSwitchId} className="block font-semibold cursor-pointer">
                                Protect sensitive data
                            </label>
                            <p className="text-secondary text-sm m-0 mt-1">
                                For emails with login codes or reset links. PostHog keeps no copy of what each email
                                contained, turns link click tracking off by default, and records only the site address
                                when click tracking is on.
                            </p>
                        </div>
                    </div>
                    <LemonSwitch
                        id={sensitiveSwitchId}
                        checked={draft.sensitive}
                        onChange={(sensitive) => updateDraft({ sensitive })}
                        data-attr="transactional-email-wizard-sensitive"
                    />
                </div>
                {draft.sensitive && (
                    <div className="border-t border-primary pt-3 mt-3 pl-8 flex items-start justify-between gap-4">
                        <div className="min-w-0">
                            <label
                                htmlFor={clickTrackingSwitchId}
                                className="block font-semibold text-sm cursor-pointer"
                            >
                                Track link clicks
                            </label>
                            <p className="text-secondary text-sm m-0 mt-1">
                                Rewrite links to count clicks. Keep this off for links carrying login or reset tokens,
                                or mark individual links with <code>data-ph-no-track</code>.
                            </p>
                        </div>
                        <LemonSwitch
                            id={clickTrackingSwitchId}
                            checked={draft.clickTrackingEnabled}
                            onChange={(clickTrackingEnabled) => updateDraft({ clickTrackingEnabled })}
                            data-attr="transactional-email-wizard-click-tracking"
                        />
                    </div>
                )}
            </LemonCard>
        </div>
    )
}
