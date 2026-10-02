import { ChangeEvent, KeyboardEvent, useState } from 'react'

import { IconCalendar, IconClock, IconCopy, IconGithub, IconGlobe, IconPlus, IconTrash, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Label,
    Switch,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    toast,
} from '@posthog/quill'

import { writeToClipboard } from 'lib/utils/writeToClipboard'

import type { LoopTriggerTypeEnumApi } from '../../../generated/api.schemas'
import {
    type LoopFormBackend,
    type LoopGithubTriggerConfig,
    type LoopGithubTriggerEvent,
    type LoopGithubTriggerPayloadFilter,
    type LoopScheduleTriggerConfig,
    type LoopTriggerDraft,
    defaultLoopTriggerOfType,
    githubTriggerActionOptions,
    isTriggerDraftValid,
    withGithubTriggerEvents,
    withGithubTriggerFilters,
} from './loopFormValues'
import {
    DEFAULT_SCHEDULE_TIME,
    type RecurringFrequency,
    compileCronSchedule,
    formatScheduleTime,
    nextScheduleRun,
    parseCronSchedule,
} from './loopSchedule'
import { LoopFormField, LoopRepositoryPicker, LoopSelect, LoopTimezoneCombobox } from './SpaceLoopFormFields'

const TRIGGER_TYPES: {
    type: LoopTriggerTypeEnumApi
    label: string
    subtitle: string
    menuDescription: string
    Icon: typeof IconCalendar
}[] = [
    {
        type: 'schedule',
        label: 'Schedule',
        subtitle: 'Runs at times you set',
        menuDescription: 'Hourly, daily, weekly or once at a set time',
        Icon: IconCalendar,
    },
    {
        type: 'github',
        label: 'GitHub event',
        subtitle: 'Runs on repository activity',
        menuDescription: 'When a repository gets a push, a pull request or issue activity',
        Icon: IconGithub,
    },
    {
        type: 'api',
        label: 'API',
        subtitle: 'Runs when your code calls an endpoint',
        menuDescription: 'An authenticated POST from your own systems',
        Icon: IconGlobe,
    },
]

/** What each backend can store. A workflow has one trigger, one GitHub event, and no payload conditions. */
const TRIGGER_LIMITS: Record<
    LoopFormBackend,
    {
        types: LoopTriggerTypeEnumApi[]
        maxTriggers: number | null
        singleGithubEvent: boolean
        payloadConditions: boolean
    }
> = {
    loops: {
        types: ['schedule', 'github', 'api'],
        maxTriggers: null,
        singleGithubEvent: false,
        payloadConditions: true,
    },
    workflow: { types: ['schedule', 'github'], maxTriggers: 1, singleGithubEvent: true, payloadConditions: false },
}

type ScheduleFrequency = RecurringFrequency | 'once'

const FREQUENCY_OPTIONS: { value: ScheduleFrequency | 'custom'; label: string }[] = [
    { value: 'hourly', label: 'Every hour' },
    { value: 'daily', label: 'Every day' },
    { value: 'weekdays', label: 'Weekdays' },
    { value: 'weekly', label: 'Every week' },
    { value: 'once', label: 'Once' },
]

const WEEKDAY_OPTIONS = [
    { value: '1', label: 'Monday' },
    { value: '2', label: 'Tuesday' },
    { value: '3', label: 'Wednesday' },
    { value: '4', label: 'Thursday' },
    { value: '5', label: 'Friday' },
    { value: '6', label: 'Saturday' },
    { value: '0', label: 'Sunday' },
]

const GITHUB_EVENT_OPTIONS: { value: LoopGithubTriggerEvent; label: string; description: string }[] = [
    { value: 'push', label: 'Push', description: 'Commits are pushed to the repository' },
    { value: 'pull_request', label: 'Pull request activity', description: 'A PR is opened, updated, merged or closed' },
    { value: 'issues', label: 'Issue activity', description: 'An issue is opened, edited or closed' },
    { value: 'issue_comment', label: 'Issue comment', description: 'A comment is added to an issue or PR' },
]

function toDatetimeLocal(iso: string): string {
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) {
        return ''
    }
    const pad = (n: number): string => String(n).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function ScheduleFields({
    config,
    disabled,
    onChange,
}: {
    config: LoopScheduleTriggerConfig
    disabled?: boolean
    onChange: (config: LoopScheduleTriggerConfig) => void
}): JSX.Element {
    const parsed = parseCronSchedule(config.cron_expression)
    // A cron the picker did not write shows as custom. Rewriting it into a picker shape would replace the real schedule.
    const isCustomCron = !config.run_at && !!config.cron_expression && !parsed
    const frequency: ScheduleFrequency | 'custom' = config.run_at
        ? 'once'
        : isCustomCron
          ? 'custom'
          : (parsed?.frequency ?? 'daily')
    const time = parsed?.time ?? DEFAULT_SCHEDULE_TIME
    const weekday = parsed?.weekday ?? '1'
    const timezone = config.timezone ?? 'UTC'
    const nextRun = nextScheduleRun(config)
    const nextRunTimezone = frequency === 'once' ? Intl.DateTimeFormat().resolvedOptions().timeZone : timezone
    const setRecurring = (next: RecurringFrequency, nextTime: string, nextWeekday: string): void =>
        onChange({ cron_expression: compileCronSchedule(next, nextTime, nextWeekday), timezone })

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
                <LoopFormField label="Frequency">
                    <LoopSelect
                        value={frequency}
                        options={
                            isCustomCron
                                ? [{ value: 'custom', label: 'Custom' }, ...FREQUENCY_OPTIONS]
                                : FREQUENCY_OPTIONS
                        }
                        onChange={(next) => {
                            if (next === 'custom') {
                                return
                            }
                            if (next === 'once') {
                                // The backend rejects a run time in the past, so the default is an hour from now.
                                onChange({ run_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(), timezone })
                                return
                            }
                            setRecurring(next, time, weekday)
                        }}
                        disabled={disabled}
                        ariaLabel="Frequency"
                        className="w-40"
                    />
                </LoopFormField>
                {(frequency === 'daily' || frequency === 'weekdays' || frequency === 'weekly') && (
                    <LoopFormField label="Time">
                        <Input
                            type="time"
                            value={time}
                            disabled={disabled}
                            aria-label="Time"
                            className="w-32"
                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                event.target.value && setRecurring(frequency, event.target.value, weekday)
                            }
                        />
                    </LoopFormField>
                )}
                {frequency === 'weekly' && (
                    <LoopFormField label="Day">
                        <LoopSelect
                            value={weekday}
                            options={WEEKDAY_OPTIONS}
                            onChange={(next) => setRecurring('weekly', time, next)}
                            disabled={disabled}
                            ariaLabel="Day of the week"
                            className="w-40"
                        />
                    </LoopFormField>
                )}
                {frequency === 'once' && (
                    <LoopFormField label="Date and time">
                        <Input
                            type="datetime-local"
                            value={config.run_at ? toDatetimeLocal(config.run_at) : ''}
                            disabled={disabled}
                            aria-label="Date and time"
                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                onChange({
                                    run_at: event.target.value ? new Date(event.target.value).toISOString() : undefined,
                                })
                            }
                        />
                    </LoopFormField>
                )}
            </div>
            {frequency === 'custom' && (
                <code className="w-fit rounded border px-2 py-1 text-xs">{config.cron_expression}</code>
            )}
            {frequency !== 'once' && (
                <LoopFormField label="Timezone">
                    <LoopTimezoneCombobox
                        value={timezone}
                        disabled={disabled}
                        onChange={(next) => onChange({ ...config, timezone: next })}
                    />
                </LoopFormField>
            )}
            {nextRun && (
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <IconClock className="size-3.5" />
                    <span>{`Next run ${formatScheduleTime(nextRun, nextRunTimezone)}`}</span>
                </span>
            )}
        </div>
    )
}

/** One value per entry, added with Enter, because a matchable GitHub value can hold a comma. */
function PayloadConditionValues({
    values,
    disabled,
    onChange,
}: {
    values: string[]
    disabled?: boolean
    onChange: (values: string[]) => void
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const commit = (): void => {
        const value = draft.trim()
        if (value && !values.includes(value)) {
            onChange([...values, value])
        }
        setDraft('')
    }
    return (
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
            {values.map((value) => (
                <Badge key={value} variant="default" className="gap-1">
                    <span>{value}</span>
                    <button
                        type="button"
                        aria-label={`Remove ${value}`}
                        disabled={disabled}
                        onClick={() => onChange(values.filter((other) => other !== value))}
                    >
                        <IconX className="size-3" />
                    </button>
                </Badge>
            ))}
            <Input
                value={draft}
                disabled={disabled}
                placeholder={values.length ? 'Add value' : 'team-security'}
                aria-label="Condition value"
                className="h-7 min-w-28 flex-1"
                onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Enter') {
                        event.preventDefault()
                        commit()
                    }
                }}
                onBlur={commit}
            />
        </div>
    )
}

function GithubFields({
    config,
    backend,
    disabled,
    onChange,
}: {
    config: LoopGithubTriggerConfig
    backend: LoopFormBackend
    disabled?: boolean
    onChange: (config: LoopGithubTriggerConfig) => void
}): JSX.Element {
    const limits = TRIGGER_LIMITS[backend]
    const offerableActions = githubTriggerActionOptions(config.events)
    // A trigger saved through the API can hold an action the form does not list. It still needs a chip to remove it.
    const actionOptions = [
        ...offerableActions,
        ...(config.filters?.actions ?? []).filter((action) => !offerableActions.includes(action)),
    ]
    const conditions = config.filters?.payload ?? []
    const setConditions = (next: LoopGithubTriggerPayloadFilter[]): void =>
        onChange(withGithubTriggerFilters(config, { payload: next }))

    return (
        <div className="flex flex-col gap-3">
            <LoopFormField label="Repository">
                <LoopRepositoryPicker
                    value={
                        config.repository
                            ? { github_integration_id: config.github_integration_id, full_name: config.repository }
                            : null
                    }
                    disabled={disabled}
                    onChange={(repository) =>
                        onChange({
                            ...config,
                            repository: repository?.full_name ?? '',
                            github_integration_id: repository?.github_integration_id ?? 0,
                        })
                    }
                />
            </LoopFormField>
            <LoopFormField label="Run when">
                <div className="flex flex-col gap-2">
                    {GITHUB_EVENT_OPTIONS.map((option) => (
                        <Label key={option.value} className="flex items-start gap-2">
                            <Checkbox
                                size="sm"
                                className="mt-0.5"
                                checked={config.events.includes(option.value)}
                                disabled={disabled}
                                onCheckedChange={(checked: boolean) => {
                                    const events = checked
                                        ? limits.singleGithubEvent
                                            ? [option.value]
                                            : [...config.events, option.value]
                                        : config.events.filter((event) => event !== option.value)
                                    onChange(withGithubTriggerEvents(config, events))
                                }}
                            />
                            <span className="flex flex-col">
                                <span className="text-sm">{option.label}</span>
                                <Text render={<span />} size="xs" variant="muted">
                                    {option.description}
                                </Text>
                            </span>
                        </Label>
                    ))}
                </div>
            </LoopFormField>
            {actionOptions.length > 0 && (
                <LoopFormField label="Actions" hint="Optional. Leave all off to run on every action.">
                    <ToggleGroup
                        multiple
                        value={config.filters?.actions ?? []}
                        onValueChange={(actions: string[]) => onChange(withGithubTriggerFilters(config, { actions }))}
                        disabled={disabled}
                        className="flex flex-wrap gap-1"
                        aria-label="Actions"
                    >
                        {actionOptions.map((action) => (
                            <ToggleGroupItem key={action} value={action} size="sm">
                                {action}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </LoopFormField>
            )}
            {limits.payloadConditions && (
                <LoopFormField
                    label="Payload conditions"
                    hint="Optional. Match any other field of the GitHub payload, like requested_team.slug for the team asked to review."
                >
                    <div className="flex flex-col gap-2">
                        {conditions.map((condition, index) => (
                            // The rows have no id and cannot move, and both inputs read from the config, so the index works.
                            // eslint-disable-next-line react/no-array-index-key
                            <div key={index} className="flex flex-wrap items-center gap-2">
                                <Input
                                    value={condition.path}
                                    disabled={disabled}
                                    placeholder="requested_team.slug"
                                    aria-label="Condition path"
                                    className="h-7 w-48"
                                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                        setConditions(
                                            conditions.map((other, i) =>
                                                i === index ? { ...other, path: event.target.value } : other
                                            )
                                        )
                                    }
                                />
                                <Text render={<span />} size="xs" variant="muted">
                                    is
                                </Text>
                                <PayloadConditionValues
                                    values={
                                        Array.isArray(condition.equals)
                                            ? condition.equals
                                            : [condition.equals].filter(Boolean)
                                    }
                                    disabled={disabled}
                                    onChange={(equals) =>
                                        setConditions(
                                            conditions.map((other, i) => (i === index ? { ...other, equals } : other))
                                        )
                                    }
                                />
                                <Button
                                    size="icon-sm"
                                    variant="outline"
                                    disabled={disabled}
                                    aria-label={
                                        condition.path ? `Remove condition ${condition.path}` : 'Remove condition'
                                    }
                                    onClick={() => setConditions(conditions.filter((_, i) => i !== index))}
                                >
                                    <IconTrash />
                                </Button>
                            </div>
                        ))}
                        <Button
                            size="sm"
                            variant="outline"
                            className="w-fit"
                            disabled={disabled}
                            onClick={() => setConditions([...conditions, { path: '', equals: [] }])}
                        >
                            <IconPlus />
                            Add condition
                        </Button>
                    </div>
                </LoopFormField>
            )}
        </div>
    )
}

function ApiFields({ endpointPath }: { endpointPath: string | null }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" variant="muted">
                Runs on an authenticated POST from your own code. Use a project secret API key (phs_…) with the
                loop:write scope. The request body becomes the run’s trigger context.
            </Text>
            {endpointPath ? (
                <div className="flex w-fit max-w-full items-center gap-2 rounded border px-2 py-1">
                    <code className="truncate text-xs">{`POST ${endpointPath}`}</code>
                    <Button
                        size="icon-xs"
                        variant="outline"
                        aria-label="Copy the endpoint"
                        onClick={async () => {
                            const outcome = await writeToClipboard(endpointPath)
                            outcome === 'copied'
                                ? toast.success({ title: 'Endpoint copied' })
                                : toast.error({ title: 'Couldn’t copy the endpoint' })
                        }}
                    >
                        <IconCopy />
                    </Button>
                </div>
            ) : (
                <Text size="xs" variant="muted">
                    Save the loop to get its endpoint.
                </Text>
            )}
        </div>
    )
}

function invalidMessage(trigger: LoopTriggerDraft, backend: LoopFormBackend): string | null {
    if (isTriggerDraftValid(trigger, backend)) {
        return null
    }
    if (trigger.type === 'github') {
        if (backend === 'workflow') {
            return 'Pick a repository and one event to finish this trigger.'
        }
        const config = trigger.config as LoopGithubTriggerConfig
        return !config.repository || !config.github_integration_id || !config.events.length
            ? 'Pick a repository and at least one event to finish this trigger.'
            : 'Fill in a path and a value for each payload condition, or remove the empty rows.'
    }
    if (trigger.type === 'api') {
        return 'A loop stored as a workflow cannot use an API trigger.'
    }
    return 'Set when this trigger runs.'
}

/** The triggers of a loop: when it runs. Mirrors PostHog Desktop's trigger editor. */
export function SpaceLoopTriggerEditor({
    triggers,
    backend,
    endpointPath,
    disabled,
    onChange,
}: {
    triggers: LoopTriggerDraft[]
    backend: LoopFormBackend
    /** The API trigger's endpoint, once the loop exists. */
    endpointPath: string | null
    disabled?: boolean
    onChange: (triggers: LoopTriggerDraft[]) => void
}): JSX.Element {
    const limits = TRIGGER_LIMITS[backend]
    const canAdd = limits.maxTriggers === null || triggers.length < limits.maxTriggers
    const update = (key: string, patch: Partial<LoopTriggerDraft>): void =>
        onChange(triggers.map((trigger) => (trigger.key === key ? { ...trigger, ...patch } : trigger)))

    return (
        <div className="flex flex-col gap-2">
            {triggers.length === 0 ? (
                <Text size="xs" variant="muted" className="px-0.5">
                    {limits.maxTriggers !== null
                        ? 'Add a trigger to choose when this loop runs.'
                        : 'This loop runs only when you start it from its page. Add a trigger to run it on its own.'}
                </Text>
            ) : (
                <ItemGroup combined>
                    {triggers.map((trigger) => {
                        const meta = TRIGGER_TYPES.find((type) => type.type === trigger.type) ?? TRIGGER_TYPES[0]
                        const message = invalidMessage(trigger, backend)
                        return (
                            <Item
                                key={trigger.key}
                                variant="outline"
                                size="sm"
                                className="flex-col items-stretch gap-3"
                            >
                                <div className="flex items-center gap-3">
                                    <ItemMedia variant="icon" className="text-muted-foreground">
                                        <meta.Icon />
                                    </ItemMedia>
                                    <ItemContent>
                                        <ItemTitle>{meta.label}</ItemTitle>
                                        <ItemDescription>{meta.subtitle}</ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        {limits.maxTriggers === null && (
                                            <Switch
                                                size="sm"
                                                checked={trigger.enabled}
                                                disabled={disabled}
                                                aria-label={
                                                    trigger.enabled ? 'Turn off this trigger' : 'Turn on this trigger'
                                                }
                                                onCheckedChange={(enabled: boolean) => update(trigger.key, { enabled })}
                                            />
                                        )}
                                        <Button
                                            size="icon-sm"
                                            variant="outline"
                                            disabled={disabled}
                                            aria-label={`Remove the ${meta.label.toLowerCase()} trigger`}
                                            onClick={() =>
                                                onChange(triggers.filter((other) => other.key !== trigger.key))
                                            }
                                        >
                                            <IconTrash />
                                        </Button>
                                    </ItemActions>
                                </div>
                                {trigger.type === 'schedule' && (
                                    <ScheduleFields
                                        config={trigger.config as LoopScheduleTriggerConfig}
                                        disabled={disabled}
                                        onChange={(config) => update(trigger.key, { config })}
                                    />
                                )}
                                {trigger.type === 'github' && (
                                    <GithubFields
                                        config={trigger.config as LoopGithubTriggerConfig}
                                        backend={backend}
                                        disabled={disabled}
                                        onChange={(config) => update(trigger.key, { config })}
                                    />
                                )}
                                {trigger.type === 'api' && <ApiFields endpointPath={endpointPath} />}
                                {message && (
                                    <Text size="xs" variant="destructive">
                                        {message}
                                    </Text>
                                )}
                            </Item>
                        )
                    })}
                </ItemGroup>
            )}
            {canAdd && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button size="sm" variant="outline" className="w-fit" disabled={disabled}>
                                <IconPlus />
                                Add trigger
                            </Button>
                        }
                    />
                    <DropdownMenuContent>
                        {TRIGGER_TYPES.filter((type) => limits.types.includes(type.type)).map((type) => (
                            <DropdownMenuItem
                                key={type.type}
                                onClick={() => onChange([...triggers, defaultLoopTriggerOfType(type.type)])}
                            >
                                <type.Icon />
                                <span className="flex flex-col">
                                    <span>{type.label}</span>
                                    <Text render={<span />} size="xs" variant="muted">
                                        {type.menuDescription}
                                    </Text>
                                </span>
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
