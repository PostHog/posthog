import { useEffect, useState } from 'react'

import { LemonButton, LemonDialog, LemonLabel, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EventsRetentionCustomFields } from './EventsRetentionCustomFields'
import { EventsPassSchedule, nextPassOn } from './nextPassOn'
import { retentionPeriodLabel } from './retentionPeriodLabel'

type RetentionChoice = 'default' | 'custom'

export interface EventsRetentionWindowFormProps {
    retentionMonths: number | null
    defaultMonths: number
    defaultSource: 'plan' | 'organization'
    defaultDeletesMonthly: boolean
    minMonths: number
    maxMonths: number
    planMonths: number
    scope: string
    overrideNote: string
    nextMonthlyCleanupOn: string
    passSchedule: EventsPassSchedule | null
    saving: boolean
    restrictionReason: string | null
    onSave: (retentionMonths: number | null) => void
    dataAttr: string
}

function formatDate(date: string): string {
    return dayjs(date).format('MMMM D, YYYY')
}

function monthsProblem(months: number | null, minMonths: number, maxMonths: number): string | null {
    if (months === null || !Number.isInteger(months)) {
        return 'Enter a whole number of months.'
    }
    if (months < minMonths || months > maxMonths) {
        return `Enter a number between ${minMonths} and ${maxMonths}.`
    }
    return null
}

function retentionChoiceOptions({
    defaultMonths,
    defaultSource,
    minMonths,
    maxMonths,
    restrictionReason,
    dataAttr,
}: EventsRetentionWindowFormProps): LemonRadioOption<RetentionChoice>[] {
    const canLengthen = maxMonths > defaultMonths
    const range = canLengthen ? 'shorter or longer' : 'shorter'
    const defaultPeriod = pluralize(defaultMonths, 'month')
    const disabledReason = restrictionReason ?? undefined
    return [
        {
            value: 'default',
            label: `${defaultSource === 'organization' ? 'Organization' : 'Default'} events retention (${defaultPeriod})`,
            description:
                defaultSource === 'organization' ? (
                    <>
                        This project uses the organization's events retention of {defaultPeriod}, which you can change
                        in{' '}
                        <Link to={urls.settings('organization-details', 'organization-events-retention')}>
                            organization settings
                        </Link>
                        . To set a {range} period for this project only, use the Custom events retention setting below.
                    </>
                ) : (
                    `Our default retention period for events data is ${defaultPeriod}. To set a ${range} period, use the Custom events retention setting below.`
                ),
            disabledReason,
            'data-attr': `${dataAttr}-default`,
        },
        {
            value: 'custom',
            label: `Custom events retention (${minMonths} to ${maxMonths} months)`,
            description: canLengthen
                ? `Set a shorter or longer period, up to ${retentionPeriodLabel(maxMonths)}, with a guaranteed deletion date.`
                : 'Set a shorter period with a guaranteed deletion date.',
            disabledReason,
            'data-attr': `${dataAttr}-custom`,
        },
    ]
}

export function EventsRetentionWindowForm(props: EventsRetentionWindowFormProps): JSX.Element {
    const {
        retentionMonths,
        defaultMonths,
        defaultDeletesMonthly,
        minMonths,
        maxMonths,
        planMonths,
        scope,
        overrideNote,
        nextMonthlyCleanupOn,
        passSchedule,
        saving,
        restrictionReason,
        onSave,
        dataAttr,
    } = props
    const savedChoice: RetentionChoice = retentionMonths === null ? 'default' : 'custom'
    const [choice, setChoice] = useState<RetentionChoice>(savedChoice)
    const [draftMonths, setDraftMonths] = useState<number | null>(retentionMonths ?? defaultMonths)

    useEffect(() => {
        setChoice(savedChoice)
        setDraftMonths(retentionMonths ?? defaultMonths)
    }, [savedChoice, retentionMonths, defaultMonths])

    const draftValue = choice === 'custom' ? draftMonths : null
    const draftProblem = choice === 'custom' ? monthsProblem(draftMonths, minMonths, maxMonths) : null
    const saveDisabledReason =
        restrictionReason ?? draftProblem ?? (draftValue === retentionMonths ? 'No changes to save' : null)

    const confirmDeletion = (months: number, description: string, onConfirm: () => void): void => {
        LemonDialog.open({
            title: `Are you sure you want to delete events that are older than ${pluralize(months, 'month')}?`,
            description,
            primaryButton: {
                children: "Yes, I'm sure",
                status: 'danger',
                onClick: onConfirm,
                'data-attr': `${dataAttr}-confirm`,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const saveCustom = (months: number): void => {
        const period = pluralize(months, 'month')
        confirmDeletion(
            months,
            `${scope} will be deleted after ${period}. If you have any events that are older than ${period}, they will be deleted at the next monthly cleanup on ${formatDate(nextMonthlyCleanupOn)} and can't be restored.`,
            () => onSave(months)
        )
    }

    const saveDefault = (): void => {
        const savedMonths = retentionMonths === null ? defaultMonths : Math.min(planMonths, retentionMonths)
        const defaultDeletes = defaultDeletesMonthly || (passSchedule?.default_window_deletes ?? true)
        if (defaultMonths >= savedMonths || !defaultDeletes) {
            onSave(null)
            return
        }
        const deletesOn = defaultDeletesMonthly ? nextMonthlyCleanupOn : passSchedule && nextPassOn(passSchedule)
        const period = pluralize(defaultMonths, 'month')
        confirmDeletion(
            defaultMonths,
            deletesOn
                ? `${scope} will be kept for the default of ${period}. Older events will be deleted at the cleanup on ${formatDate(deletesOn)} and can't be restored.`
                : `${scope} will be kept for the default of ${period}. Older events will be deleted at least 3 months from now and can't be restored.`,
            () => onSave(null)
        )
    }

    const save = (): void => {
        if (saveDisabledReason) {
            return
        }
        if (draftValue === null) {
            saveDefault()
        } else {
            saveCustom(draftValue)
        }
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <LemonLabel>Retention period</LemonLabel>
            <LemonRadio<RetentionChoice>
                value={choice}
                onChange={(value) => {
                    setChoice(value)
                    setDraftMonths(retentionMonths ?? defaultMonths)
                }}
                radioPosition="top"
                aria-label="Retention period"
                data-attr={`${dataAttr}-choice`}
                options={retentionChoiceOptions(props)}
            />
            {choice === 'custom' && (
                <EventsRetentionCustomFields
                    months={draftMonths}
                    problem={draftProblem}
                    minMonths={minMonths}
                    maxMonths={maxMonths}
                    planMonths={planMonths}
                    overrideNote={overrideNote}
                    disabled={!!restrictionReason || saving}
                    onChange={setDraftMonths}
                    onPressEnter={save}
                    dataAttr={dataAttr}
                />
            )}
            <div>
                <LemonButton
                    type="primary"
                    onClick={save}
                    loading={saving}
                    disabledReason={saveDisabledReason}
                    data-attr={`${dataAttr}-save`}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
