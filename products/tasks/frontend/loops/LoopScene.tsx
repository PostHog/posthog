import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import { IconPause, IconPlay } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Field,
    FieldError,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Switch,
    Text,
    Textarea,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SettingsSection } from '../components/SettingsSection'
import type { LoopWriteVisibilityEnumApi } from '../generated/api.schemas'
import { LoopTriggerMode, describeTrigger, loopPausedDescription } from './loopForm'
import { LoopRepositoryField } from './LoopRepositoryField'
import { LoopRuns } from './LoopRuns'
import { LoopSceneLogicProps, loopSceneLogic } from './loopSceneLogic'
import { LoopScheduleField } from './LoopScheduleField'

export const scene: SceneExport<LoopSceneLogicProps> = {
    component: LoopScene,
    logic: loopSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

const VISIBILITY_OPTIONS: { value: LoopWriteVisibilityEnumApi; label: string }[] = [
    { value: 'personal', label: 'Only you' },
    { value: 'team', label: 'Everyone in the project' },
]

const TRIGGER_OPTIONS: { value: LoopTriggerMode; label: string }[] = [
    { value: 'schedule', label: 'On a schedule' },
    { value: 'api', label: 'When an API call arrives' },
    { value: 'manual', label: 'Only when you run it' },
]

/** Keeps the row's label on the left until the control no longer fits beside it, then stacks the row. */
const ROW_CONTENT_CLASS = 'min-w-56'

export function LoopScene({ id }: LoopSceneLogicProps): JSX.Element {
    const railEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const loopsEnabled = useFeatureFlag('LOOPS')
    const logic = loopSceneLogic({ id })
    const {
        currentTeamId,
        isNew,
        loop,
        loopLoading,
        loopMissing,
        loopUnavailable,
        formValues,
        formError,
        showErrors,
        patch,
        saving,
        saveDisabledReason,
        running,
        runDisabledReason,
        togglingEnabled,
        deleting,
        ownerOnlyDisabledReason,
    } = useValues(logic)
    const { setFormValues, saveLoop, resetForm, runLoop, setEnabled, deleteLoop, loadLoop } = useActions(logic)

    if (!railEnabled || !loopsEnabled || loopMissing) {
        return <NotFound object="loop" />
    }
    if (!isNew && !loop) {
        if (loopUnavailable && !loopLoading) {
            return (
                <SceneContent>
                    <Empty className="py-12" data-quill>
                        <EmptyHeader>
                            <EmptyTitle>This loop didn’t load</EmptyTitle>
                            <EmptyDescription>Check your connection and try again.</EmptyDescription>
                        </EmptyHeader>
                        <EmptyContent>
                            <Button variant="outline" onClick={() => loadLoop()} data-attr="loop-retry">
                                Try again
                            </Button>
                        </EmptyContent>
                    </Empty>
                </SceneContent>
            )
        }
        return (
            <SceneContent>
                <SceneTitleSection name={null} isLoading resourceType={{ type: 'task' }} />
                <div className="flex w-full max-w-200 flex-col gap-7" aria-busy="true" data-quill>
                    {[1, 2, 3].map((section) => (
                        <div key={section} className="flex flex-col gap-2">
                            <Skeleton className="h-4 w-28" />
                            <Skeleton className="h-14 w-full" />
                        </div>
                    ))}
                </div>
            </SceneContent>
        )
    }

    const dirty = isNew || Object.keys(patch).length > 0
    const nameError = showErrors && !formValues.name.trim() ? formError : null
    const instructionsError = showErrors && !nameError ? formError : null
    const pausedDescription = loop ? loopPausedDescription(loop) : null
    const triggerUrl =
        loop && currentTeamId
            ? `${window.location.origin}/api/projects/${currentTeamId}/loops/${loop.id}/trigger/`
            : null

    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name={isNew ? 'New loop' : (loop?.name ?? null)}
                    description={
                        isNew
                            ? 'A loop starts an agent task on a schedule, from an API call, or when you run it.'
                            : null
                    }
                    resourceType={{ type: 'task' }}
                    actions={
                        loop ? (
                            <div className="flex flex-wrap items-center gap-2" data-quill>
                                <Button
                                    variant="outline"
                                    loading={togglingEnabled}
                                    onClick={() => setEnabled(!loop.enabled)}
                                    data-attr={loop.enabled ? 'loop-pause' : 'loop-resume'}
                                >
                                    {loop.enabled ? <IconPause /> : <IconPlay />}
                                    {loop.enabled ? 'Pause' : 'Resume'}
                                </Button>
                                <Tooltip disabled={!runDisabledReason}>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="primary"
                                                loading={running}
                                                disabled={!!runDisabledReason}
                                                onClick={() => runLoop()}
                                                data-attr="loop-run-now"
                                            />
                                        }
                                    >
                                        Run now
                                    </TooltipTrigger>
                                    <TooltipContent>{runDisabledReason}</TooltipContent>
                                </Tooltip>
                            </div>
                        ) : undefined
                    }
                />
                <div className="flex w-full max-w-200 flex-col gap-7 pb-8" data-quill>
                    {loop && !loop.enabled && (
                        <Text size="xs" variant="muted" role="status">
                            {pausedDescription ??
                                'This loop is paused. Its triggers don’t start runs until you resume it.'}
                        </Text>
                    )}

                    <SettingsSection label="General">
                        <ItemGroup combined>
                            <Item variant="outline" size="sm">
                                <ItemContent className={ROW_CONTENT_CLASS}>
                                    <ItemTitle id="loop-name-label">Name</ItemTitle>
                                    <ItemDescription>Shown in the sidebar and on each run.</ItemDescription>
                                </ItemContent>
                                <Field className="w-64 max-w-full" data-invalid={!!nameError || undefined}>
                                    <Input
                                        value={formValues.name}
                                        placeholder="Weekly dependency check"
                                        maxLength={400}
                                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                            setFormValues({ name: event.target.value })
                                        }
                                        aria-labelledby="loop-name-label"
                                        aria-invalid={!!nameError || undefined}
                                        data-attr="loop-name"
                                    />
                                    {nameError && <FieldError>{nameError}</FieldError>}
                                </Field>
                            </Item>
                            <Item variant="outline" size="sm">
                                <ItemContent className={ROW_CONTENT_CLASS}>
                                    <ItemTitle id="loop-visibility-label">Who can see it</ItemTitle>
                                    <ItemDescription>
                                        {ownerOnlyDisabledReason ??
                                            'Everyone in the project can see and run a shared loop.'}
                                    </ItemDescription>
                                </ItemContent>
                                <ItemActions>
                                    <Select<LoopWriteVisibilityEnumApi>
                                        items={VISIBILITY_OPTIONS}
                                        value={formValues.visibility}
                                        onValueChange={(visibility: LoopWriteVisibilityEnumApi | null) =>
                                            visibility && setFormValues({ visibility })
                                        }
                                        disabled={!!ownerOnlyDisabledReason}
                                    >
                                        <SelectTrigger
                                            aria-labelledby="loop-visibility-label"
                                            data-attr="loop-visibility"
                                        >
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {VISIBILITY_OPTIONS.map((option) => (
                                                <SelectItem key={option.value} value={option.value}>
                                                    {option.label}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </ItemActions>
                            </Item>
                        </ItemGroup>
                    </SettingsSection>

                    <SettingsSection
                        label="Instructions"
                        description={ownerOnlyDisabledReason ?? 'The agent gets these instructions on every run.'}
                    >
                        <Field data-invalid={!!instructionsError || undefined}>
                            <Textarea
                                rows={8}
                                value={formValues.instructions}
                                placeholder="Check for outdated dependencies and open a pull request that updates them."
                                disabled={!!ownerOnlyDisabledReason}
                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                    setFormValues({ instructions: event.target.value })
                                }
                                aria-label="Instructions"
                                aria-invalid={!!instructionsError || undefined}
                                data-attr="loop-instructions"
                            />
                            {instructionsError && <FieldError>{instructionsError}</FieldError>}
                        </Field>
                    </SettingsSection>

                    <SettingsSection label="When it runs" description={ownerOnlyDisabledReason}>
                        {formValues.triggerMode === null && loop ? (
                            <div className="flex flex-col gap-2">
                                <ItemGroup combined>
                                    {loop.triggers.map((trigger) => (
                                        <Item key={trigger.id} variant="outline" size="sm">
                                            <ItemContent className="min-w-0">
                                                <ItemTitle className="truncate">{describeTrigger(trigger)}</ItemTitle>
                                                {!trigger.enabled && <ItemDescription>Turned off</ItemDescription>}
                                            </ItemContent>
                                        </Item>
                                    ))}
                                </ItemGroup>
                                <Text size="xs" variant="muted">
                                    Edit these triggers in PostHog Desktop.
                                </Text>
                            </div>
                        ) : (
                            <div className="flex flex-col gap-3">
                                <Select<LoopTriggerMode>
                                    items={TRIGGER_OPTIONS}
                                    value={formValues.triggerMode}
                                    onValueChange={(triggerMode: LoopTriggerMode | null) =>
                                        triggerMode &&
                                        setFormValues({
                                            triggerMode,
                                            // A trigger of another type is a new trigger, so the old one is removed.
                                            triggerId:
                                                loop?.triggers.find((trigger) => trigger.type === triggerMode)?.id ??
                                                null,
                                        })
                                    }
                                    disabled={!!ownerOnlyDisabledReason}
                                >
                                    <SelectTrigger
                                        className="w-64 max-w-full"
                                        aria-label="When it runs"
                                        data-attr="loop-trigger-mode"
                                    >
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {TRIGGER_OPTIONS.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                {formValues.triggerMode === 'schedule' && (
                                    <LoopScheduleField
                                        schedule={formValues.schedule}
                                        timezone={formValues.timezone}
                                        disabled={!!ownerOnlyDisabledReason}
                                        onChange={(schedule) => setFormValues({ schedule })}
                                    />
                                )}
                                {formValues.triggerMode === 'api' && (
                                    <Text size="xs" variant="muted" className="break-all">
                                        {triggerUrl && formValues.triggerId
                                            ? `Send a POST request to ${triggerUrl} with a project secret API key that has the loop:write scope. The request body is passed to the agent.`
                                            : 'Save the loop to get the URL that starts a run.'}
                                    </Text>
                                )}
                            </div>
                        )}
                    </SettingsSection>

                    <SettingsSection
                        label="Repository"
                        description={
                            ownerOnlyDisabledReason ??
                            'The agent works in this repository. Leave it empty for a loop that only reports.'
                        }
                    >
                        <LoopRepositoryField
                            repository={formValues.repository}
                            disabled={!!ownerOnlyDisabledReason}
                            onChange={(repository) => setFormValues({ repository })}
                        />
                    </SettingsSection>

                    {formValues.repository && (
                        <SettingsSection label="Pull requests" description={ownerOnlyDisabledReason}>
                            <ItemGroup combined>
                                <Item variant="outline" size="sm">
                                    <ItemContent className={ROW_CONTENT_CLASS}>
                                        <ItemTitle id="loop-create-prs-label">Open pull requests</ItemTitle>
                                        <ItemDescription>
                                            Let the agent push a branch and open a pull request with its changes.
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Switch
                                            checked={formValues.createPullRequests}
                                            onCheckedChange={(createPullRequests: boolean) =>
                                                setFormValues({
                                                    createPullRequests,
                                                    autoFixPullRequests:
                                                        createPullRequests && formValues.autoFixPullRequests,
                                                })
                                            }
                                            disabled={!!ownerOnlyDisabledReason}
                                            aria-labelledby="loop-create-prs-label"
                                            data-attr="loop-create-prs"
                                        />
                                    </ItemActions>
                                </Item>
                                <Item variant="outline" size="sm">
                                    <ItemContent className={ROW_CONTENT_CLASS}>
                                        <ItemTitle id="loop-auto-fix-label">Fix CI and review comments</ItemTitle>
                                        <ItemDescription>
                                            {formValues.createPullRequests
                                                ? 'Watch CI on the pull request and address review comments.'
                                                : 'Turn on Open pull requests to use this.'}
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Switch
                                            checked={formValues.autoFixPullRequests}
                                            onCheckedChange={(autoFixPullRequests: boolean) =>
                                                setFormValues({ autoFixPullRequests })
                                            }
                                            disabled={!!ownerOnlyDisabledReason || !formValues.createPullRequests}
                                            aria-labelledby="loop-auto-fix-label"
                                            data-attr="loop-auto-fix"
                                        />
                                    </ItemActions>
                                </Item>
                            </ItemGroup>
                        </SettingsSection>
                    )}

                    <div className="flex flex-wrap items-center gap-2">
                        <Tooltip disabled={!saveDisabledReason || saving}>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="primary"
                                        loading={saving}
                                        disabled={!!saveDisabledReason}
                                        onClick={() => saveLoop()}
                                        data-attr={isNew ? 'loop-create' : 'loop-save'}
                                    />
                                }
                            >
                                {isNew ? 'Create loop' : 'Save changes'}
                            </TooltipTrigger>
                            <TooltipContent>{saveDisabledReason}</TooltipContent>
                        </Tooltip>
                        {!isNew && dirty && (
                            <Button
                                variant="outline"
                                disabled={saving}
                                onClick={() => resetForm()}
                                data-attr="loop-discard"
                            >
                                Discard changes
                            </Button>
                        )}
                    </div>

                    {loop && <LoopRuns id={id} />}

                    {loop && (
                        <SettingsSection label="Danger zone">
                            <ItemGroup combined>
                                <Item variant="outline" size="sm">
                                    <ItemContent className={ROW_CONTENT_CLASS}>
                                        <ItemTitle>Delete loop</ItemTitle>
                                        <ItemDescription>
                                            This stops all its triggers. Tasks from past runs stay.
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <AlertDialog>
                                            <AlertDialogTrigger
                                                render={
                                                    <Button
                                                        variant="destructive"
                                                        loading={deleting}
                                                        data-attr="loop-delete"
                                                    />
                                                }
                                            >
                                                Delete loop
                                            </AlertDialogTrigger>
                                            <AlertDialogContent>
                                                <AlertDialogHeader>
                                                    <AlertDialogTitle>{`Delete ${loop.name}?`}</AlertDialogTitle>
                                                    <AlertDialogDescription>
                                                        The loop stops running for everyone. Only its owner or a project
                                                        admin can delete it.
                                                    </AlertDialogDescription>
                                                </AlertDialogHeader>
                                                <AlertDialogFooter>
                                                    <AlertDialogClose render={<Button variant="outline" />}>
                                                        Cancel
                                                    </AlertDialogClose>
                                                    <AlertDialogClose
                                                        render={
                                                            <Button
                                                                variant="destructive-outline"
                                                                onClick={() => deleteLoop()}
                                                                data-attr="loop-delete-confirm"
                                                            />
                                                        }
                                                    >
                                                        Delete
                                                    </AlertDialogClose>
                                                </AlertDialogFooter>
                                            </AlertDialogContent>
                                        </AlertDialog>
                                    </ItemActions>
                                </Item>
                            </ItemGroup>
                        </SettingsSection>
                    )}
                </div>
            </SceneContent>
        </TooltipProvider>
    )
}
