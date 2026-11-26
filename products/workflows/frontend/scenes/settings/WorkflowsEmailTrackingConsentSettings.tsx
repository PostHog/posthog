import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, RadioGroup, RadioGroupItem } from '@posthog/quill'

import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamWorkflowsConfigApi } from '~/generated/core/api.schemas'

type ConsentMode = NonNullable<TeamWorkflowsConfigApi['email_tracking_consent_mode']>

const CONSENT_MODE_OPTIONS: LemonRadioOption<ConsentMode>[] = [
    {
        value: 'off',
        label: 'No consent enforcement',
        description:
            'Opens and clicks are tracked according to each email step\'s "Track opens and link clicks" setting.',
    },
    {
        value: 'opt_out',
        label: 'Opt-out',
        description:
            'Track by default, but not for recipients who have objected to tracking. Marketing emails only; transactional emails are exempt.',
    },
    {
        value: 'opt_in',
        label: 'Opt-in',
        description:
            'Only track recipients who have explicitly consented. Recipients without a stored consent are sent untracked emails. Marketing emails only; transactional emails are exempt.',
    },
]

export function WorkflowsEmailTrackingConsentSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const todayRailNav = useQuillSurface()
    const idPrefix = useId()

    const mode: ConsentMode = currentTeam?.workflows_config?.email_tracking_consent_mode ?? 'off'

    const handleChange = (value: ConsentMode): void => {
        updateCurrentTeam({
            workflows_config: {
                email_tracking_consent_mode: value,
            },
        })
    }

    if (todayRailNav) {
        return (
            <RadioGroup
                value={mode}
                onValueChange={(next) => handleChange(next as ConsentMode)}
                disabled={currentTeamLoading}
                className="w-fit"
            >
                {CONSENT_MODE_OPTIONS.map((option) => {
                    const optionId = `${idPrefix}-${option.value}`

                    return (
                        <Field key={option.value} orientation="horizontal">
                            <RadioGroupItem id={optionId} value={option.value} />
                            <FieldContent>
                                <FieldLabel htmlFor={optionId}>{option.label}</FieldLabel>
                                <FieldDescription>{option.description}</FieldDescription>
                            </FieldContent>
                        </Field>
                    )
                })}
            </RadioGroup>
        )
    }

    return (
        <LemonRadio
            value={mode}
            onChange={handleChange}
            options={CONSENT_MODE_OPTIONS}
            className={currentTeamLoading ? 'opacity-50 pointer-events-none' : undefined}
        />
    )
}
