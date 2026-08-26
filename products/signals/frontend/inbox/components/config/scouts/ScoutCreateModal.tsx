import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'
import { SKILL_NAME_MAX_LENGTH } from 'products/skills/frontend/skillConstants'

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
import { ScoutMcpServersPicker } from './ScoutMcpServersPicker'
import { ScoutSlackDestination } from './ScoutSlackDestination'

export interface ScoutCreateModalProps {
    isOpen: boolean
    onClose: () => void
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
}

export function ScoutCreateModal({ isOpen, onClose, initialValues, onCreated }: ScoutCreateModalProps): JSX.Element {
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const logicKey = useId()
    const formId = `scout-create-form-${logicKey}`
    const logicProps: ScoutCreateModalLogicProps = { logicKey, initialValues, onClose, onCreated }
    const logic = scoutCreateModalLogic(logicProps)
    const {
        isScoutCreateFormSubmitting,
        scoutCreateForm,
        scoutCreateFormChanged,
        scoutCreateFormValidationErrors,
        scoutCreateFormTouches,
        showScoutCreateFormErrors,
    } = useValues(logic)
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
    // Field errors only render after a submit attempt, and the submit button is disabled while the
    // form has errors, so a name typo would otherwise surface only as the button's tooltip. Show the
    // name error in the help slot as soon as the field has been left, until the form shows it itself.
    const touchedNameError =
        scoutCreateFormTouches.name && !showScoutCreateFormErrors ? scoutCreateFormValidationErrors.name : undefined
    const firstError = [
        scoutCreateFormValidationErrors.name,
        scoutCreateFormValidationErrors.description,
        scoutCreateFormValidationErrors.body,
        scoutCreateFormValidationErrors.dailyTime,
        scoutCreateFormValidationErrors.config?.run_interval_minutes,
        tagsValidationError,
    ].find((error): error is string => typeof error === 'string')

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title="Create a scout"
            description="Define what the scout should investigate and how often it should run."
            width={720}
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
                        disabledReason={firstError}
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
                <div className="flex flex-col gap-4">
                    <LemonField
                        name="name"
                        label="Name"
                        help={
                            !redesign ? (
                                <>
                                    Scout names start with{' '}
                                    <span className="font-mono text-[11px]">{SIGNALS_SCOUT_SKILL_PREFIX}</span>.
                                </>
                            ) : touchedNameError ? (
                                <span className="text-danger">{touchedNameError}</span>
                            ) : (
                                'Lowercase letters, numbers, and hyphens.'
                            )
                        }
                    >
                        {redesign ? (
                            <LemonInput
                                autoFocus
                                // The prefix is fixed and shown in the field, so the limit is what is left for the typed part.
                                maxLength={SKILL_NAME_MAX_LENGTH - SIGNALS_SCOUT_SKILL_PREFIX.length}
                                prefix={
                                    <span className="font-mono text-xs text-muted">{SIGNALS_SCOUT_SKILL_PREFIX}</span>
                                }
                                placeholder="checkout-failures"
                                data-attr="scout-create-name"
                            />
                        ) : (
                            <LemonInput
                                autoFocus
                                maxLength={64}
                                placeholder="signals-scout-checkout-failures"
                                data-attr="scout-create-name"
                            />
                        )}
                    </LemonField>

                    <LemonField
                        name="description"
                        label="Description"
                        help="A short summary of the signal or behavior this scout investigates."
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
                                    disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                                    data-attr="scout-create-tags"
                                />
                                {tagsValidationError ? <LemonField.Error error={tagsValidationError} /> : null}
                            </div>
                        )}
                    </LemonField>

                    <LemonField name="body" label="Instructions" help="This markdown prompt is executed on every run.">
                        <LemonTextArea
                            minRows={8}
                            maxRows={16}
                            className="font-mono text-xs"
                            placeholder="Describe the signals, thresholds, investigation steps, and reporting criteria."
                            data-attr="scout-create-instructions"
                        />
                    </LemonField>

                    <LemonField name="config.mcp_gateway_server_ids">
                        {({ value, onChange }) => (
                            <ScoutMcpServersPicker
                                selectedServerIds={value ?? []}
                                onChange={onChange}
                                disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                            />
                        )}
                    </LemonField>

                    <div className="flex flex-col gap-3 border-t border-primary pt-4">
                        <span className="font-medium text-sm">Run settings</span>
                        <LemonField.Pure
                            label="Schedule"
                            help={
                                scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                                    ? 'A cron schedule provided by the opening context'
                                    : 'Choose a rolling cadence, or a set time each day'
                            }
                        >
                            <LemonSelect
                                value={scheduleMode}
                                options={getScoutScheduleOptions(scoutCreateForm.config)}
                                onChange={setScoutCreateScheduleMode}
                            />
                        </LemonField.Pure>
                        {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ? (
                            <LemonField.Pure label="Run time" help={`Uses the project timezone (${projectTimezone})`}>
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
                                    disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                                />
                            )}
                        </LemonField>
                        <LemonField
                            name="config.emit"
                            help="Turn this off for a dry run. The scout still runs on its schedule, and its signals stay out of the inbox."
                        >
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    label="Write signals to the inbox"
                                    bordered
                                    fullWidth
                                    disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                                />
                            )}
                        </LemonField>
                        <LemonField name="config.output_destinations">
                            {({ value, onChange }) => (
                                <ScoutSlackDestination
                                    destination={value?.slack}
                                    onChange={onChange}
                                    disabledReason={isScoutCreateFormSubmitting ? 'Creating the scout' : undefined}
                                />
                            )}
                        </LemonField>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
