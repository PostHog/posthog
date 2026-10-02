import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useState } from 'react'

import { IconGithub } from '@posthog/icons'
import {
    Button,
    Checkbox,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    Text,
} from '@posthog/quill'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { spaceLabel, todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { getEffortsForModel, getModelLabel, pickerModels } from 'products/posthog_ai/frontend/utils/composerModels'

import { MAX_ATTACHED_SKILLS, taskSkillsPickerLogic } from '../../../components/TaskSkillsPicker/taskSkillsPickerLogic'
import type {
    EventsEnumApi,
    LoopRepositoryEntryApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from '../../../generated/api.schemas'
import { DEFAULT_MODEL_BY_RUNTIME_ADAPTER } from '../../../modelCatalog.generated'
import type {
    LoopContextOutputs,
    LoopContextTargetDraft,
    LoopFormBackend,
    LoopFormValues,
    LoopNotificationChannel,
    LoopNotifications,
} from './loopFormValues'

/** A labeled control in the form, with an optional hint under it. */
export function LoopFormField({
    label,
    hint,
    htmlFor,
    children,
}: {
    label: string
    hint?: ReactNode
    htmlFor?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor={htmlFor} className="text-xs font-medium">
                {label}
            </Label>
            {children}
            {hint && (
                <Text size="xs" variant="muted">
                    {hint}
                </Text>
            )}
        </div>
    )
}

export interface LoopSelectOption<T extends string> {
    value: T
    label: string
}

export function LoopSelect<T extends string>({
    value,
    options,
    onChange,
    disabled,
    ariaLabel,
    className,
}: {
    value: T
    options: LoopSelectOption<T>[]
    onChange: (value: T) => void
    disabled?: boolean
    ariaLabel: string
    className?: string
}): JSX.Element {
    return (
        <Select<T>
            items={options}
            value={value}
            onValueChange={(next: T | null) => next !== null && onChange(next)}
            disabled={disabled}
        >
            <SelectTrigger aria-label={ariaLabel} className={className ?? 'w-full max-w-90'}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

function currentPathForReturn(): string {
    return window.location.pathname + window.location.search + window.location.hash
}

/**
 * The team's GitHub repositories. Loops run against the project's GitHub App installations, so a pick saves the
 * installation id with the repository.
 */
export function LoopRepositoryPicker({
    value,
    onChange,
    disabled,
}: {
    value: LoopRepositoryEntryApi | null
    onChange: (value: LoopRepositoryEntryApi | null) => void
    disabled?: boolean
}): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])
    const [browsedIntegrationId, setBrowsedIntegrationId] = useState<number | null>(null)
    const integrationId =
        browsedIntegrationId ??
        (value?.github_integration_id && githubIntegrations.some((i) => i.id === value.github_integration_id)
            ? value.github_integration_id
            : githubIntegrations[0]?.id)

    if (integrationsLoading) {
        return (
            <Button variant="outline" disabled className="w-fit">
                <IconGithub />
                GitHub
            </Button>
        )
    }
    if (!githubIntegrations.length || !integrationId) {
        return (
            <Button
                variant="outline"
                className="w-fit"
                render={
                    <LinkPrimitive
                        to={api.integrations.authorizeUrl({ kind: 'github', next: currentPathForReturn() })}
                        disableClientSideRouting
                    />
                }
                data-attr="today-space-loop-form-connect-github"
            >
                <IconGithub />
                Connect GitHub
            </Button>
        )
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            {githubIntegrations.length > 1 && (
                <LoopSelect
                    value={String(integrationId)}
                    options={githubIntegrations.map((integration) => ({
                        value: String(integration.id),
                        label: integration.display_name,
                    }))}
                    onChange={(id) => setBrowsedIntegrationId(Number(id))}
                    disabled={disabled}
                    ariaLabel="GitHub organization"
                    className="w-48"
                />
            )}
            <GitHubRepositoryCombobox
                integrationId={integrationId}
                value={value?.full_name ?? ''}
                onChange={(repository) =>
                    onChange(repository ? { github_integration_id: integrationId, full_name: repository } : null)
                }
                disabled={disabled}
                showNoneOption
            />
        </div>
    )
}

function timezones(): string[] {
    const intl = Intl as { supportedValuesOf?: (key: 'timeZone') => string[] }
    return intl.supportedValuesOf?.('timeZone') ?? ['UTC']
}

export function LoopTimezoneCombobox({
    value,
    onChange,
    disabled,
}: {
    value: string
    onChange: (value: string) => void
    disabled?: boolean
}): JSX.Element {
    const options = useMemo(() => {
        const all = timezones()
        return all.includes(value) ? all : [value, ...all]
    }, [value])
    return (
        <Combobox
            items={options}
            value={value}
            onValueChange={(next: string | null) => next && onChange(next)}
            disabled={disabled}
        >
            <ComboboxInput placeholder="Search timezones" aria-label="Timezone" className="w-full max-w-72" />
            <ComboboxContent>
                <ComboboxEmpty>No timezone matches.</ComboboxEmpty>
                <ComboboxList>
                    {(timezone: string) => (
                        <ComboboxItem key={timezone} value={timezone}>
                            {timezone}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

const DEFAULT_MODEL_VALUE = '__default__'
const AUTO_EFFORT_VALUE = 'auto'

const ADAPTER_OPTIONS: LoopSelectOption<RuntimeAdapterEnumApi>[] = [
    { value: 'claude', label: 'Claude Code' },
    { value: 'codex', label: 'Codex' },
]

/**
 * The model, harness and reasoning effort. Options come from the same catalog as the task composer, so every
 * pick passes the server's checks. A switch that drops support for the effort resets it to Auto.
 */
export function LoopModelFields({
    values,
    formBackend,
    disabled,
    onPatch,
}: {
    values: LoopFormValues
    formBackend: LoopFormBackend
    disabled?: boolean
    onPatch: (patch: Partial<LoopFormValues>) => void
}): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)
    const adapterEditable = formBackend === 'loops'
    const adapter = values.runtimeAdapter
    const defaultModel = DEFAULT_MODEL_BY_RUNTIME_ADAPTER[adapter]
    const models = useMemo(
        () => pickerModels(catalogue, values.model).filter((choice) => choice.runtime_adapter === adapter),
        [catalogue, values.model, adapter]
    )
    // A workflow stores the effort next to a pinned model only, so it offers no effort for the default model.
    const effortNeedsModel = !adapterEditable && !values.model
    const efforts = effortNeedsModel ? [] : getEffortsForModel(catalogue, values.model || defaultModel)
    const clampEffort = (model: string, effort: ReasoningEffortEnumApi | null): ReasoningEffortEnumApi | null => {
        if (!effort || (!adapterEditable && !model)) {
            return null
        }
        return getEffortsForModel(catalogue, model || defaultModel).some((option) => option.value === effort)
            ? effort
            : null
    }

    return (
        <div className="flex flex-col gap-4">
            <LoopFormField label="Model" hint="Default lets PostHog pick the model for each run. Choose one to pin it.">
                <LoopSelect
                    value={values.model || DEFAULT_MODEL_VALUE}
                    options={[
                        {
                            value: DEFAULT_MODEL_VALUE,
                            label: `Default (${getModelLabel(catalogue, defaultModel)})`,
                        },
                        ...models.map((choice) => ({ value: choice.model, label: choice.display_name })),
                    ]}
                    onChange={(next) => {
                        const model = next === DEFAULT_MODEL_VALUE ? '' : next
                        onPatch({ model, reasoningEffort: clampEffort(model, values.reasoningEffort) })
                    }}
                    disabled={disabled}
                    ariaLabel="Model"
                />
            </LoopFormField>
            <div className="flex flex-wrap gap-4">
                {adapterEditable && (
                    <LoopFormField label="Harness">
                        <LoopSelect
                            value={adapter}
                            options={ADAPTER_OPTIONS}
                            onChange={(runtimeAdapter) =>
                                // The harnesses have separate model lists, so a pinned model cannot carry over.
                                onPatch({ runtimeAdapter, model: '', reasoningEffort: null })
                            }
                            disabled={disabled}
                            ariaLabel="Harness"
                            className="w-48"
                        />
                    </LoopFormField>
                )}
                <LoopFormField
                    label="Reasoning effort"
                    hint={effortNeedsModel ? 'Pick a model to set the reasoning effort.' : undefined}
                >
                    <LoopSelect
                        value={values.reasoningEffort ?? AUTO_EFFORT_VALUE}
                        options={[
                            { value: AUTO_EFFORT_VALUE, label: 'Auto' },
                            ...efforts.map((effort) => ({ value: effort.value, label: effort.label })),
                        ]}
                        onChange={(next) =>
                            onPatch({
                                reasoningEffort: next === AUTO_EFFORT_VALUE ? null : (next as ReasoningEffortEnumApi),
                            })
                        }
                        disabled={disabled || effortNeedsModel}
                        ariaLabel="Reasoning effort"
                        className="w-48"
                    />
                </LoopFormField>
            </div>
        </div>
    )
}

const NOTIFICATION_EVENTS: { value: EventsEnumApi; label: string }[] = [
    { value: 'run_completed', label: 'Run completed' },
    { value: 'run_failed', label: 'Run failed' },
    { value: 'pr_created', label: 'PR created' },
    { value: 'pr_merged', label: 'PR merged' },
    { value: 'pr_closed', label: 'PR closed' },
    { value: 'needs_attention', label: 'Needs attention' },
]

function NotificationRow({
    title,
    description,
    channel,
    disabled,
    onChange,
    children,
}: {
    title: string
    description: string
    channel: LoopNotificationChannel
    disabled?: boolean
    onChange: (patch: Partial<LoopNotificationChannel>) => void
    children?: ReactNode
}): JSX.Element {
    return (
        <Item variant="outline" size="sm" className="flex-col items-stretch">
            <div className="flex items-center gap-3">
                <ItemContent>
                    <ItemTitle>{title}</ItemTitle>
                    <ItemDescription>{description}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Switch
                        size="sm"
                        checked={channel.enabled}
                        disabled={disabled}
                        aria-label={`${title} notifications`}
                        onCheckedChange={(checked: boolean) =>
                            onChange({
                                enabled: checked,
                                events:
                                    checked && !channel.events.length
                                        ? NOTIFICATION_EVENTS.map((event) => event.value)
                                        : channel.events,
                            })
                        }
                    />
                </ItemActions>
            </div>
            {channel.enabled && (
                <div className="flex flex-col gap-2 pt-2">
                    <div className="flex flex-wrap gap-x-4 gap-y-2">
                        {NOTIFICATION_EVENTS.map((event) => (
                            <Label key={event.value} className="flex items-center gap-1.5 text-xs">
                                <Checkbox
                                    size="sm"
                                    checked={channel.events.includes(event.value)}
                                    disabled={disabled}
                                    onCheckedChange={(checked: boolean) =>
                                        onChange({
                                            events: checked
                                                ? [...channel.events, event.value]
                                                : channel.events.filter((value) => value !== event.value),
                                        })
                                    }
                                />
                                <span>{event.label}</span>
                            </Label>
                        ))}
                    </div>
                    {children}
                </div>
            )}
        </Item>
    )
}

function SlackChannelCombobox({
    integrationId,
    channelId,
    disabled,
    onChange,
}: {
    integrationId: number
    channelId: string | null
    disabled?: boolean
    onChange: (channel: { id: string; name: string } | null) => void
}): JSX.Element {
    const logic = slackIntegrationLogic({ id: integrationId })
    const { slackChannelsForPicker, allSlackChannelsLoading } = useValues(logic)
    const { loadAllSlackChannels } = useActions(logic)
    useEffect(() => {
        loadAllSlackChannels()
    }, [loadAllSlackChannels])
    const channels = slackChannelsForPicker.filter((channel) => !!channel.name)
    const names = new Map(channels.map((channel) => [channel.id, channel.name ?? channel.id]))
    return (
        <Combobox
            items={channels.map((channel) => channel.id)}
            value={channelId}
            onValueChange={(next: string | null) => onChange(next ? { id: next, name: names.get(next) ?? next } : null)}
            itemToStringLabel={(id: string) => `#${names.get(id) ?? id}`}
            disabled={disabled}
        >
            <ComboboxInput
                placeholder={allSlackChannelsLoading ? 'Loading channels…' : 'Pick a channel'}
                aria-label="Slack channel"
                className="w-full max-w-72"
            />
            <ComboboxContent>
                <ComboboxEmpty>No channel matches.</ComboboxEmpty>
                <ComboboxList>
                    {(id: string) => (
                        <ComboboxItem key={id} value={id}>
                            {`#${names.get(id) ?? id}`}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

/** Push, email and Slack messages about runs. Only the loops API stores them. */
export function LoopNotificationsFields({
    notifications,
    disabled,
    onChange,
}: {
    notifications: LoopNotifications
    disabled?: boolean
    onChange: (notifications: LoopNotifications) => void
}): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const slackIntegrations = getIntegrationsByKind(['slack'])
    const update = (key: keyof LoopNotifications, patch: Partial<LoopNotificationChannel>): void =>
        onChange({ ...notifications, [key]: { ...notifications[key], ...patch } })
    const slackParams = notifications.slack.params as {
        integration_id?: number
        channel_id?: string
        channel_name?: string
    }
    const slackIntegrationId = slackParams.integration_id ?? slackIntegrations[0]?.id ?? null

    return (
        <ItemGroup combined>
            <NotificationRow
                title="Push"
                description="Sent to the loop owner’s devices"
                channel={notifications.push}
                disabled={disabled}
                onChange={(patch) => update('push', patch)}
            />
            <NotificationRow
                title="Email"
                description="Sent to the loop owner"
                channel={notifications.email}
                disabled={disabled}
                onChange={(patch) => update('email', patch)}
            />
            <NotificationRow
                title="Slack"
                description="A summary in a channel"
                channel={notifications.slack}
                disabled={disabled}
                onChange={(patch) => update('slack', patch)}
            >
                {slackIntegrationId === null ? (
                    <Button
                        variant="outline"
                        size="sm"
                        className="w-fit"
                        render={
                            <LinkPrimitive
                                to={api.integrations.authorizeUrl({ kind: 'slack', next: currentPathForReturn() })}
                                disableClientSideRouting
                            />
                        }
                    >
                        Connect Slack
                    </Button>
                ) : (
                    <div className="flex flex-wrap items-center gap-2">
                        {slackIntegrations.length > 1 && (
                            <LoopSelect
                                value={String(slackIntegrationId)}
                                options={slackIntegrations.map((integration) => ({
                                    value: String(integration.id),
                                    label: integration.display_name,
                                }))}
                                onChange={(id) => update('slack', { params: { integration_id: Number(id) } })}
                                disabled={disabled}
                                ariaLabel="Slack workspace"
                                className="w-48"
                            />
                        )}
                        <SlackChannelCombobox
                            integrationId={slackIntegrationId}
                            channelId={slackParams.channel_id ?? null}
                            disabled={disabled}
                            onChange={(channel) =>
                                update('slack', {
                                    params: channel
                                        ? {
                                              integration_id: slackIntegrationId,
                                              channel_id: channel.id,
                                              channel_name: channel.name,
                                          }
                                        : { integration_id: slackIntegrationId },
                                })
                            }
                        />
                    </div>
                )}
            </NotificationRow>
        </ItemGroup>
    )
}

function OutputRow({
    title,
    description,
    checked,
    disabled,
    onChange,
    children,
}: {
    title: string
    description: string
    checked: boolean
    disabled?: boolean
    onChange: (checked: boolean) => void
    children?: ReactNode
}): JSX.Element {
    return (
        <Item variant="outline" size="sm" className="flex-col items-stretch">
            <div className="flex items-center gap-3">
                <ItemContent>
                    <ItemTitle>{title}</ItemTitle>
                    <ItemDescription>{description}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Switch
                        size="sm"
                        checked={checked}
                        disabled={disabled}
                        aria-label={title}
                        onCheckedChange={(next: boolean) => onChange(next)}
                    />
                </ItemActions>
            </div>
            {children && <div className="pt-2">{children}</div>}
        </Item>
    )
}

/**
 * The space the loop files its runs in. A loops API loop can also keep the space's context.md or a canvas up
 * to date. A workflow loop only posts to the feed.
 */
export function LoopContextField({
    value,
    canvases,
    showOutputs,
    disabled,
    onChange,
}: {
    value: LoopContextTargetDraft | null
    canvases: CanvasApi[]
    showOutputs: boolean
    disabled?: boolean
    onChange: (value: LoopContextTargetDraft) => void
}): JSX.Element {
    const { spaces } = useValues(todaySpacesLogic)
    const options = spaces.map((space) => ({ value: space.id, label: spaceLabel(space) }))
    if (value && !options.some((option) => option.value === value.spaceId)) {
        options.unshift({ value: value.spaceId, label: value.name || 'This space' })
    }
    const patchOutputs = (outputs: Partial<LoopContextOutputs>): void => {
        if (value) {
            onChange({ ...value, outputs: { ...value.outputs, ...outputs } })
        }
    }
    return (
        <div className="flex flex-col gap-3">
            <LoopSelect
                value={value?.spaceId ?? ''}
                options={options}
                onChange={(spaceId) =>
                    // The toggles carry over, but a canvas belongs to the old space.
                    onChange({
                        spaceId,
                        name: options.find((option) => option.value === spaceId)?.label ?? '',
                        outputs: {
                            ...(value?.outputs ?? { post_to_feed: true, update_context: false }),
                            canvas_id: null,
                        },
                    })
                }
                disabled={disabled}
                ariaLabel="Space"
            />
            {value && showOutputs && (
                <ItemGroup combined>
                    <OutputRow
                        title="Show runs in the feed"
                        description="Each run shows as a session in the space’s feed."
                        checked={value.outputs.post_to_feed}
                        disabled={disabled}
                        onChange={(post_to_feed) => patchOutputs({ post_to_feed })}
                    />
                    <OutputRow
                        title="Keep context.md up to date"
                        description="Each run reads the space’s context.md and publishes it again with the latest state."
                        checked={value.outputs.update_context}
                        disabled={disabled}
                        onChange={(update_context) => patchOutputs({ update_context })}
                    />
                    <OutputRow
                        title="Keep a canvas up to date"
                        description={
                            canvases.length
                                ? 'Each run rewrites a canvas in the space with fresh content.'
                                : 'This space has no canvases yet. Create one first.'
                        }
                        checked={!!value.outputs.canvas_id}
                        disabled={disabled || !canvases.length}
                        onChange={(checked) => patchOutputs({ canvas_id: checked ? (canvases[0]?.id ?? null) : null })}
                    >
                        {value.outputs.canvas_id ? (
                            <LoopSelect
                                value={value.outputs.canvas_id}
                                options={canvases.map((canvas) => ({
                                    value: canvas.id,
                                    label: canvas.name || 'Untitled canvas',
                                }))}
                                onChange={(canvas_id) => patchOutputs({ canvas_id })}
                                disabled={disabled}
                                ariaLabel="Canvas"
                            />
                        ) : undefined}
                    </OutputRow>
                </ItemGroup>
            )}
        </div>
    )
}

/** Team skills a workflow loop gives the agent. The workflow reads them from the team's skill store on each run. */
export function LoopTeamSkillsField({
    value,
    disabled,
    onChange,
}: {
    value: string[]
    disabled?: boolean
    onChange: (value: string[]) => void
}): JSX.Element {
    const { skillOptions, skillOptionsLoading } = useValues(taskSkillsPickerLogic)
    const { ensureOptionsLoaded, setSearch } = useActions(taskSkillsPickerLogic)
    useEffect(() => {
        ensureOptionsLoaded()
    }, [ensureOptionsLoaded])
    const names = [...new Set([...value, ...skillOptions.map((skill) => skill.name)])]
    return (
        <LoopFormField
            label="Skills"
            hint={`Optional. Up to ${MAX_ATTACHED_SKILLS} skills from your team’s skill store.`}
        >
            <Combobox
                multiple
                items={names}
                value={value}
                onValueChange={(next: string[]) => onChange(next.slice(0, MAX_ATTACHED_SKILLS))}
                onInputValueChange={(next: string) => setSearch(next)}
                disabled={disabled}
            >
                <ComboboxInput
                    placeholder={
                        value.length ? value.join(', ') : skillOptionsLoading ? 'Loading skills…' : 'Add skills'
                    }
                    aria-label="Skills"
                    className="w-full max-w-90"
                />
                <ComboboxContent>
                    <ComboboxEmpty>No skill matches.</ComboboxEmpty>
                    <ComboboxList>
                        {(name: string) => (
                            <ComboboxItem key={name} value={name}>
                                {name}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        </LoopFormField>
    )
}
