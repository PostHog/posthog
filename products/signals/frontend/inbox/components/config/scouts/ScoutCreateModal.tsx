import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId, type ReactNode } from 'react'

import { IconBell, IconClock, IconCode, IconPencil, IconPlus, IconSparkles } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import {
    ScoutCreateInitialValues,
    ScoutCreateModalLogicProps,
    scoutCreateModalLogic,
} from '../../../logics/scoutCreateModalLogic'
import {
    getScoutScheduleMode,
    getScoutScheduleOptions,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    SIGNALS_SCOUT_SKILL_PREFIX,
} from '../../../utils/scoutRunsWindow'
import { MAX_SCOUT_TAGS, normalizeScoutTags } from '../../../utils/scoutTags'
import { ScoutGitHubConnection } from './ScoutGitHubConnection'
import { ScoutSlackDestination } from './ScoutSlackDestination'

export interface ScoutCreateModalProps {
    isOpen: boolean
    onClose: () => void
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
    title?: string
    description?: string
    showGitHubConnection?: boolean
    githubSetupNextUrl?: string
}

interface ScoutFormSectionProps {
    title: string
    description: string
    icon: ReactNode
    children: ReactNode
}

function ScoutFormSection({ title, description, icon, children }: ScoutFormSectionProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="overflow-hidden p-0 shadow-none">
            <div className="flex items-start gap-3 border-b border-primary bg-surface-secondary p-4">
                <span className="flex size-8 shrink-0 items-center justify-center rounded border border-primary bg-surface-primary text-secondary [&_svg]:size-4">
                    {icon}
                </span>
                <div className="min-w-0">
                    <h4 className="m-0">{title}</h4>
                    <p className="m-0 mt-0.5 text-xs text-secondary">{description}</p>
                </div>
            </div>
            <div className="flex flex-col gap-4 p-4">{children}</div>
        </LemonCard>
    )
}

export function ScoutCreateModal({
    isOpen,
    onClose,
    initialValues,
    onCreated,
    title = 'Create a scout',
    description = 'Choose what the scout monitors and how it reports findings.',
    showGitHubConnection = false,
    githubSetupNextUrl,
}: ScoutCreateModalProps): JSX.Element {
    const logicKey = useId()
    const formId = `scout-create-form-${logicKey}`
    const logicProps: ScoutCreateModalLogicProps = { logicKey, initialValues, onClose, onCreated }
    const logic = scoutCreateModalLogic(logicProps)
    const { isScoutCreateFormSubmitting, scoutCreateForm, scoutCreateFormChanged, scoutCreateFormValidationErrors } =
        useValues(logic)
    const { resetScoutCreateForm, setScoutCreateDailyTime, setScoutCreateScheduleMode } = useActions(logic)
    const { timezone: projectTimezone } = useValues(teamLogic)
    const scheduleMode = getScoutScheduleMode(scoutCreateForm.config)

    const handleClose = (): void => {
        if (isScoutCreateFormSubmitting) {
            return
        }
        resetScoutCreateForm()
        onClose()
    }

    const tagsValidationError = scoutCreateFormValidationErrors.config?.tags?.find(
        (error): error is string => typeof error === 'string'
    )
    const firstError = [
        scoutCreateFormValidationErrors.name,
        scoutCreateFormValidationErrors.description,
        scoutCreateFormValidationErrors.body,
        scoutCreateFormValidationErrors.dailyTime,
        scoutCreateFormValidationErrors.config?.run_interval_minutes,
        tagsValidationError,
    ].find((error): error is string => typeof error === 'string')
    const creationDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={
                <div className="flex items-center gap-2.5">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded bg-accent-highlight-secondary text-accent">
                        <IconSparkles className="text-lg" />
                    </span>
                    <span>{title}</span>
                </div>
            }
            description={description}
            width={880}
            hasUnsavedInput={scoutCreateFormChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                        onClick={handleClose}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isScoutCreateFormSubmitting}
                        disabledReason={creationDisabledReason ?? firstError}
                        icon={<IconPlus />}
                    >
                        Create scout
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={scoutCreateModalLogic}
                props={logicProps}
                formKey="scoutCreateForm"
                id={formId}
                enableFormOnSubmit
            >
                <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]">
                    <div className="flex min-w-0 flex-col gap-4">
                        <ScoutFormSection
                            title="Scout details"
                            description="Name this scout and make it easy to find later."
                            icon={<IconPencil />}
                        >
                            <LemonField
                                name="name"
                                label="Name"
                                help={
                                    <>
                                        Scout names start with{' '}
                                        <span className="font-mono text-[11px]">{SIGNALS_SCOUT_SKILL_PREFIX}</span>.
                                    </>
                                }
                            >
                                <LemonInput
                                    autoFocus
                                    maxLength={64}
                                    placeholder="signals-scout-checkout-failures"
                                    data-attr="scout-create-name"
                                />
                            </LemonField>

                            <LemonField
                                name="description"
                                label="Description"
                                help="Summarize the signal or behavior this scout investigates."
                            >
                                <LemonTextArea
                                    minRows={2}
                                    maxRows={4}
                                    maxLength={4096}
                                    placeholder="Investigates recurring checkout failures and reports meaningful changes."
                                    data-attr="scout-create-description"
                                />
                            </LemonField>

                            <LemonField
                                name="config.tags"
                                label="Tags"
                                help={`Add up to ${MAX_SCOUT_TAGS} tags to group scouts in the fleet.`}
                            >
                                {({ value, onChange }) => (
                                    <div className="flex flex-col gap-2">
                                        <LemonInputSelect
                                            mode="multiple"
                                            allowCustomValues
                                            limit={MAX_SCOUT_TAGS}
                                            value={value}
                                            onChange={(tags) => onChange(normalizeScoutTags(tags))}
                                            placeholder="Add tag"
                                            fullWidth
                                            status={tagsValidationError ? 'danger' : 'default'}
                                            disabledReason={
                                                isScoutCreateFormSubmitting ? 'Creating the scout' : undefined
                                            }
                                            data-attr="scout-create-tags"
                                        />
                                        {tagsValidationError ? <LemonField.Error error={tagsValidationError} /> : null}
                                    </div>
                                )}
                            </LemonField>
                        </ScoutFormSection>

                        <ScoutFormSection
                            title="Instructions"
                            description="Describe what the scout should check and when it should report a finding."
                            icon={<IconCode />}
                        >
                            <LemonField
                                name="body"
                                label="Instructions"
                                help="These markdown instructions run on every check."
                            >
                                <LemonTextArea
                                    minRows={10}
                                    maxRows={18}
                                    className="font-mono text-xs"
                                    placeholder="Describe the signals, thresholds, investigation steps, and reporting criteria."
                                    data-attr="scout-create-instructions"
                                />
                            </LemonField>
                        </ScoutFormSection>
                    </div>

                    <div className="flex min-w-0 flex-col gap-4">
                        <ScoutFormSection
                            title="Run schedule"
                            description="Choose when the scout checks for new findings."
                            icon={<IconClock />}
                        >
                            <LemonField.Pure
                                label="Schedule"
                                help={
                                    scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                                        ? 'Uses the schedule provided when this form opened.'
                                        : 'Choose an interval or a set time each day.'
                                }
                            >
                                <LemonSelect
                                    fullWidth
                                    value={scheduleMode}
                                    options={getScoutScheduleOptions(scoutCreateForm.config)}
                                    onChange={setScoutCreateScheduleMode}
                                />
                            </LemonField.Pure>
                            {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ? (
                                <LemonField.Pure
                                    label="Run time"
                                    help={`Uses the project timezone (${projectTimezone})`}
                                >
                                    <LemonInput
                                        type="time"
                                        step={60}
                                        value={scoutCreateForm.dailyTime}
                                        onChange={setScoutCreateDailyTime}
                                    />
                                </LemonField.Pure>
                            ) : null}
                            <LemonField name="config.enabled">
                                {({ value, onChange }) => (
                                    <LemonSwitch
                                        checked={value}
                                        onChange={onChange}
                                        label="Enable this scout"
                                        bordered
                                        fullWidth
                                    />
                                )}
                            </LemonField>
                            <LemonField name="config.emit">
                                {({ value, onChange }) => (
                                    <LemonSwitch
                                        checked={value}
                                        onChange={onChange}
                                        label="Write signals to the inbox"
                                        bordered
                                        fullWidth
                                    />
                                )}
                            </LemonField>
                            <span className="text-xs text-muted">
                                Turn off inbox signals to run the scout in dry-run mode.
                            </span>
                        </ScoutFormSection>

                        <ScoutFormSection
                            title="Connections"
                            description="Optionally send findings to Slack or let the scout work with code."
                            icon={<IconBell />}
                        >
                            {showGitHubConnection ? (
                                <ScoutGitHubConnection githubSetupNextUrl={githubSetupNextUrl} />
                            ) : null}
                            <div className="rounded border border-primary bg-surface-secondary p-3">
                                <LemonField name="config.output_destinations">
                                    {({ value, onChange }) => (
                                        <ScoutSlackDestination
                                            destination={value?.slack}
                                            onChange={onChange}
                                            disabledReason={
                                                isScoutCreateFormSubmitting ? 'Creating the scout' : undefined
                                            }
                                            embedded
                                        />
                                    )}
                                </LemonField>
                            </div>
                        </ScoutFormSection>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
