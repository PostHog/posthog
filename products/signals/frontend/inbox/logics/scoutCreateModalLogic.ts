import { LogicWrapper, MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'
import { signalsScoutCreate } from 'products/signals/frontend/generated/api'
import type {
    SignalScoutConfigOptionsApi,
    SignalScoutCreateApi,
    SignalScoutCreateResponseApi,
} from 'products/signals/frontend/generated/api.schemas'
import { SKILL_DESCRIPTION_MAX_LENGTH, validateSkillName } from 'products/skills/frontend/skillConstants'

import { isInboxRedesignEnabled } from '../utils/inboxRedesign'
import {
    dailyCronToTime,
    DEFAULT_SCOUT_DAILY_TIME,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    SIGNALS_SCOUT_SKILL_PREFIX,
    stripScoutPrefix,
    timeToDailyCron,
} from '../utils/scoutRunsWindow'
import { MAX_SCOUT_TAG_LENGTH, MAX_SCOUT_TAGS, normalizeScoutTag } from '../utils/scoutTags'
import { scoutMcpServersLogic } from './scoutMcpServersLogic'

type ScoutCreateConfigFormValues = Required<
    Pick<
        SignalScoutConfigOptionsApi,
        'enabled' | 'emit' | 'run_interval_minutes' | 'run_cron_schedule' | 'tags' | 'mcp_gateway_server_ids'
    >
> &
    Pick<SignalScoutConfigOptionsApi, 'output_destinations'>

export type ScoutCreateFormValues = Pick<SignalScoutCreateApi, 'name' | 'description' | 'body'> & {
    config: ScoutCreateConfigFormValues
    dailyTime: string
}

export type ScoutCreateInitialValues = Partial<Pick<SignalScoutCreateApi, 'name' | 'description' | 'body'>> & {
    config?: Partial<ScoutCreateConfigFormValues>
}

export interface ScoutCreateModalLogicProps {
    logicKey: string
    initialValues?: ScoutCreateInitialValues
    onClose: () => void
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
}

export const DEFAULT_SCOUT_CREATE_FORM_VALUES: ScoutCreateFormValues = {
    name: '',
    description: '',
    body: '',
    dailyTime: DEFAULT_SCOUT_DAILY_TIME,
    config: {
        enabled: true,
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: null,
        tags: [],
        mcp_gateway_server_ids: [],
    },
}

/**
 * Under the redesign the form holds the part after `signals-scout-` and the input shows the prefix;
 * callers (deep links, templates) may pass a full skill name. With the flag off the form holds the
 * whole skill name, prefix included, as it always did.
 */
export function getScoutCreateFormValues(
    initialValues: ScoutCreateInitialValues | undefined,
    redesign: boolean
): ScoutCreateFormValues {
    const config = {
        ...DEFAULT_SCOUT_CREATE_FORM_VALUES.config,
        ...initialValues?.config,
    }
    return {
        ...DEFAULT_SCOUT_CREATE_FORM_VALUES,
        ...initialValues,
        name: redesign
            ? stripScoutPrefix((initialValues?.name ?? '').trim())
            : (initialValues?.name ?? SIGNALS_SCOUT_SKILL_PREFIX),
        config,
        dailyTime: dailyCronToTime(config.run_cron_schedule) ?? DEFAULT_SCOUT_DAILY_TIME,
    }
}

/**
 * The skill name a form entry produces: the fixed prefix plus what was typed. A pasted full name
 * (`signals-scout-foo`) is not doubled up.
 */
export function scoutSkillNameFromInput(name: string): string {
    return `${SIGNALS_SCOUT_SKILL_PREFIX}${stripScoutPrefix(name.trim())}`
}

function isValidScoutDailyTime(dailyTime: string): boolean {
    return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(dailyTime)
}

function scoutNameError(name: string, redesign: boolean): string | undefined {
    if (!redesign) {
        const normalizedName = name.trim()
        const validationError = validateSkillName(normalizedName)
        if (validationError) {
            return validationError
        }
        if (!normalizedName.startsWith(SIGNALS_SCOUT_SKILL_PREFIX)) {
            return `Name must start with ${SIGNALS_SCOUT_SKILL_PREFIX}`
        }
        return undefined
    }
    const bareName = stripScoutPrefix(name.trim())
    if (!bareName) {
        return 'Name is required'
    }
    // The shared skill-name rule rejects spaces too, but as "lowercase letters, numbers, and hyphens
    // only", which does not tell someone who typed "checkout failures" what to change.
    if (/\s/.test(bareName)) {
        return 'Name cannot contain spaces. Use hyphens between words.'
    }
    return validateSkillName(`${SIGNALS_SCOUT_SKILL_PREFIX}${bareName}`)
}

function scoutTagsError(tags: string[]): string | undefined {
    if (tags.length > MAX_SCOUT_TAGS) {
        return `A scout can have up to ${MAX_SCOUT_TAGS} tags`
    }
    if (tags.some((tag) => normalizeScoutTag(tag).length > MAX_SCOUT_TAG_LENGTH)) {
        return `Tags can be up to ${MAX_SCOUT_TAG_LENGTH} characters`
    }
    return undefined
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutCreateModalLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    teamScoutServers: MCPServiceAccountServerApi[] // scoutMcpServersLogic
    currentTeamId: number | null // teamLogic
    isScoutCreateFormSubmitting: boolean
    isScoutCreateFormValid: boolean
    mcpServersDefaulted: boolean
    scoutCreateForm: ScoutCreateFormValues
    scoutCreateFormAllErrors: Record<string, any>
    scoutCreateFormChanged: boolean
    scoutCreateFormErrors: DeepPartialMap<ScoutCreateFormValues, ValidationErrorType>
    scoutCreateFormHasErrors: boolean
    scoutCreateFormManualErrors: Record<string, any>
    scoutCreateFormTouched: boolean
    scoutCreateFormTouches: Record<string, boolean>
    scoutCreateFormValidationErrors: DeepPartialMap<ScoutCreateFormValues, ValidationErrorType>
    showScoutCreateFormErrors: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutCreateModalLogicActions {
    markMcpServersDefaulted: () => {
        value: true
    }
    resetScoutCreateForm: (values?: ScoutCreateFormValues) => {
        values?: ScoutCreateFormValues
    }
    setScoutCreateDailyTime: (dailyTime: string) => {
        dailyTime: string
    }
    setScoutCreateFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setScoutCreateFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setScoutCreateFormValues: (values: DeepPartial<ScoutCreateFormValues>) => {
        values: DeepPartial<ScoutCreateFormValues>
    }
    setScoutCreateScheduleMode: (scheduleMode: string) => {
        scheduleMode: string
    }
    submitScoutCreateForm: () => {
        value: boolean
    }
    submitScoutCreateFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitScoutCreateFormRequest: (scoutCreateForm: ScoutCreateFormValues) => {
        scoutCreateForm: ScoutCreateFormValues
    }
    submitScoutCreateFormSuccess: (scoutCreateForm: ScoutCreateFormValues) => {
        scoutCreateForm: ScoutCreateFormValues
    }
    touchScoutCreateFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutCreateModalLogicMeta {
    key: string
}

export type scoutCreateModalLogicType = MakeLogicType<
    scoutCreateModalLogicValues,
    scoutCreateModalLogicActions,
    ScoutCreateModalLogicProps,
    scoutCreateModalLogicMeta
>

export const scoutCreateModalLogic: LogicWrapper<scoutCreateModalLogicType> = kea<scoutCreateModalLogicType>([
    path(['scenes', 'inbox', 'logics', 'scoutCreateModalLogic']),
    props({} as ScoutCreateModalLogicProps),
    key((logicProps) => logicProps.logicKey),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            scoutMcpServersLogic,
            ['teamScoutServers'],
        ],
    })),
    actions({
        setScoutCreateScheduleMode: (scheduleMode: string) => ({ scheduleMode }),
        setScoutCreateDailyTime: (dailyTime: string) => ({ dailyTime }),
        markMcpServersDefaulted: true,
    }),
    reducers(({ props: logicProps }) => ({
        // A caller that passes explicit server ids opts out of the "all servers" default.
        mcpServersDefaulted: [
            logicProps.initialValues?.config?.mcp_gateway_server_ids !== undefined,
            {
                markMcpServersDefaulted: () => true,
            },
        ],
    })),
    forms(({ props: logicProps, actions, values }) => ({
        scoutCreateForm: {
            defaults: getScoutCreateFormValues(logicProps.initialValues, isInboxRedesignEnabled(values.featureFlags)),
            errors: ({ name, description, body, config, dailyTime }) => {
                const runIntervalError =
                    !Number.isFinite(config.run_interval_minutes) ||
                    config.run_interval_minutes < 30 ||
                    config.run_interval_minutes > 43200
                        ? 'Schedule must be between 30 minutes and 30 days'
                        : undefined
                const tagsError = scoutTagsError(config.tags)

                return {
                    name: scoutNameError(name, isInboxRedesignEnabled(values.featureFlags)),
                    description: !description.trim()
                        ? 'Description is required'
                        : description.length > SKILL_DESCRIPTION_MAX_LENGTH
                          ? `Description must be ${SKILL_DESCRIPTION_MAX_LENGTH} characters or fewer`
                          : undefined,
                    body: !body.trim() ? 'Instructions are required' : undefined,
                    dailyTime:
                        dailyCronToTime(config.run_cron_schedule) !== null && !isValidScoutDailyTime(dailyTime)
                            ? 'Run time is required'
                            : undefined,
                    config:
                        runIntervalError || tagsError
                            ? { run_interval_minutes: runIntervalError, tags: tagsError ? [tagsError] : undefined }
                            : undefined,
                }
            },
            submit: async (formValues) => {
                if (values.currentTeamId === null) {
                    lemonToast.error('Select a project before creating a scout')
                    throw new Error('No project selected')
                }

                try {
                    const scout = await signalsScoutCreate(String(values.currentTeamId), {
                        name: isInboxRedesignEnabled(values.featureFlags)
                            ? scoutSkillNameFromInput(formValues.name)
                            : formValues.name.trim(),
                        description: formValues.description.trim(),
                        body: formValues.body.trim(),
                        config: formValues.config,
                    })

                    actions.resetScoutCreateForm()
                    lemonToast.success(
                        scout.created ? 'Scout created' : 'Scout already exists. Its settings were updated.'
                    )
                    logicProps.onCreated?.(scout)
                    logicProps.onClose()
                } catch (error) {
                    const apiError = error instanceof ApiError ? error : null
                    if (apiError?.status === 409 || apiError?.attr === 'name') {
                        actions.setScoutCreateFormManualErrors({
                            name: apiError.detail ?? 'A scout with this name already exists',
                        })
                    } else {
                        lemonToast.error(apiError?.detail ?? 'Could not create the scout')
                    }
                    throw error
                }
            },
        },
    })),
    // The team's servers load asynchronously, so the default is applied once they arrive
    // rather than in the form defaults. Applying it once keeps a later reload from
    // re-selecting servers the user switched off.
    subscriptions(({ actions, values }) => ({
        teamScoutServers: (teamScoutServers: MCPServiceAccountServerApi[]) => {
            if (values.mcpServersDefaulted || teamScoutServers.length === 0) {
                return
            }
            actions.markMcpServersDefaulted()
            const mcpGatewayServerIds = teamScoutServers.map((server) => server.id)
            if (values.scoutCreateFormChanged) {
                // The user edited the form before the servers loaded, so keep the changed flag.
                actions.setScoutCreateFormValue('config.mcp_gateway_server_ids', mcpGatewayServerIds)
                return
            }
            // Apply the default through a reset so the pre-selection keeps the form pristine. A form
            // marked changed blocks the overlay-close click and shows a false "unsaved input" warning.
            actions.resetScoutCreateForm({
                ...values.scoutCreateForm,
                config: { ...values.scoutCreateForm.config, mcp_gateway_server_ids: mcpGatewayServerIds },
            })
        },
    })),
    listeners(({ actions, values }) => ({
        setScoutCreateScheduleMode: ({ scheduleMode }) => {
            if (scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE) {
                return
            }
            if (scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE) {
                const dailyTime = isValidScoutDailyTime(values.scoutCreateForm.dailyTime)
                    ? values.scoutCreateForm.dailyTime
                    : DEFAULT_SCOUT_DAILY_TIME
                actions.setScoutCreateFormValues({
                    dailyTime,
                    config: {
                        ...values.scoutCreateForm.config,
                        run_cron_schedule: timeToDailyCron(dailyTime),
                    },
                })
                return
            }

            const runIntervalMinutes = Number(scheduleMode)
            if (!Number.isFinite(runIntervalMinutes)) {
                return
            }
            actions.setScoutCreateFormValues({
                config: {
                    ...values.scoutCreateForm.config,
                    run_interval_minutes: runIntervalMinutes,
                    run_cron_schedule: null,
                },
            })
        },
        setScoutCreateDailyTime: ({ dailyTime }) => {
            if (!isValidScoutDailyTime(dailyTime)) {
                actions.setScoutCreateFormValues({ dailyTime })
                return
            }
            actions.setScoutCreateFormValues({
                dailyTime,
                config: {
                    ...values.scoutCreateForm.config,
                    run_cron_schedule: timeToDailyCron(dailyTime),
                },
            })
        },
    })),
])
