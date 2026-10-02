import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
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
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SpaceSettingsSection } from '../../SpaceSettingsSection'
import { isAutoFixEnabled, withAutoFix } from './loopFormValues'
import {
    LoopContextField,
    LoopFormField,
    LoopModelFields,
    LoopNotificationsFields,
    LoopRepositoryPicker,
    LoopSelect,
    LoopTeamSkillsField,
} from './SpaceLoopFormFields'
import { SpaceLoopFormLogicProps, spaceLoopFormLogic } from './spaceLoopFormLogic'
import { SpaceLoopTriggerEditor } from './SpaceLoopTriggerEditor'

export const scene: SceneExport<SpaceLoopFormLogicProps> = {
    component: SpaceLoopFormScene,
    logic: spaceLoopFormLogic,
    paramsToProps: ({ params: { id, loopId } }) => ({ id, loopId }),
}

const VISIBILITY_OPTIONS = [
    { value: 'personal' as const, label: 'Personal' },
    { value: 'team' as const, label: 'Team' },
]

const DEFAULT_SANDBOX_VALUE = '__default__'

/** Creates or edits a loop, with the same fields as PostHog Desktop's loop form. */
export function SpaceLoopFormScene({ id, loopId }: SpaceLoopFormLogicProps): JSX.Element {
    const railNavEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const loopsEnabled = useFeatureFlag('LOOPS')
    const logic = spaceLoopFormLogic({ id, loopId })
    const {
        values,
        formBackend,
        ready,
        isEdit,
        foreign,
        source,
        sourceLoading,
        sourceMissing,
        sourceUnavailable,
        submitting,
        submitDisabledReason,
        sandboxEnvironments,
        sandboxEnvironmentsLoading,
        spaceCanvases,
        discardOpen,
        backend,
    } = useValues(logic)
    const { patch, submit, cancel, setDiscardOpen, leave, loadSource } = useActions(logic)

    if (!railNavEnabled || !loopsEnabled || sourceMissing) {
        return <NotFound object="loop" />
    }

    const workflow = formBackend === 'workflow'
    const disabled = submitting || foreign
    const title = isEdit ? `Edit ${values.name || 'loop'}` : 'New loop'
    const endpointPath =
        isEdit && backend && !workflow ? `/api/projects/${backend.projectId}/loops/${loopId}/trigger/` : null
    const sandboxOptions = [
        { value: DEFAULT_SANDBOX_VALUE, label: 'Default environment' },
        ...sandboxEnvironments.map((environment) => ({ value: environment.id, label: environment.name })),
    ]
    if (values.sandboxEnvironmentId && !sandboxOptions.some((option) => option.value === values.sandboxEnvironmentId)) {
        sandboxOptions.push({ value: values.sandboxEnvironmentId, label: 'Unavailable environment' })
    }

    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name={ready ? title : null}
                    isLoading={!ready}
                    resourceType={{ type: 'task' }}
                    forceBackTo={
                        loopId
                            ? {
                                  key: [Scene.TaskSpaceLoop, loopId],
                                  name: values.name || 'Loop',
                                  path: urls.taskSpaceLoop(id, loopId),
                              }
                            : { key: [Scene.TaskSpace, `${id}/loops`], name: 'Loops', path: urls.taskSpaceLoops(id) }
                    }
                />
                <div className="flex w-full max-w-200 flex-col gap-7 pb-8" data-quill>
                    {!ready ? (
                        sourceUnavailable ? (
                            <Empty className="border border-dashed py-8">
                                <EmptyHeader>
                                    <EmptyTitle>This loop didn’t load</EmptyTitle>
                                    <EmptyDescription>Check your connection and try again.</EmptyDescription>
                                </EmptyHeader>
                                <EmptyContent>
                                    <Button
                                        variant="outline"
                                        loading={sourceLoading}
                                        onClick={() => loadSource()}
                                        data-attr="today-space-loop-form-retry"
                                    >
                                        Try again
                                    </Button>
                                </EmptyContent>
                            </Empty>
                        ) : (
                            <div aria-hidden className="flex flex-col gap-7">
                                <Skeleton className="h-40 w-full" />
                                <Skeleton className="h-32 w-full" />
                            </div>
                        )
                    ) : (
                        <>
                            {foreign && (
                                <Item variant="outline" size="sm">
                                    <ItemContent>
                                        <ItemTitle>This loop was changed in the workflow editor</ItemTitle>
                                        <ItemDescription>
                                            The form can’t show everything the workflow does, so a save here would
                                            replace that work. Change it in Workflows instead.
                                        </ItemDescription>
                                    </ItemContent>
                                    <ItemActions>
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            render={
                                                <LinkPrimitive to={urls.workflow(source?.loopId ?? '', 'workflow')} />
                                            }
                                        >
                                            Open in Workflows
                                        </Button>
                                    </ItemActions>
                                </Item>
                            )}

                            <SpaceSettingsSection
                                label="Prompt"
                                description="Name the loop and write what the agent does on each run."
                            >
                                <div className="flex flex-col gap-4">
                                    <LoopFormField label="Name" htmlFor="loop-form-name">
                                        <Input
                                            id="loop-form-name"
                                            value={values.name}
                                            placeholder="Daily standup summary"
                                            disabled={disabled}
                                            className="max-w-90"
                                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                                patch({ name: event.target.value })
                                            }
                                            data-attr="today-space-loop-form-name"
                                        />
                                    </LoopFormField>
                                    <LoopFormField label="Description" htmlFor="loop-form-description">
                                        <Textarea
                                            id="loop-form-description"
                                            value={values.description}
                                            placeholder="A short summary shown in the list of loops"
                                            disabled={disabled}
                                            rows={2}
                                            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                                patch({ description: event.target.value })
                                            }
                                        />
                                    </LoopFormField>
                                    {values.skill ? (
                                        <>
                                            <Item variant="outline" size="sm">
                                                <ItemContent>
                                                    <ItemTitle>{`Runs the /${values.skill.name} skill`}</ItemTitle>
                                                    <ItemDescription>
                                                        PostHog Desktop attached this skill. Detach it to write
                                                        instructions instead.
                                                    </ItemDescription>
                                                </ItemContent>
                                                <ItemActions>
                                                    <Button
                                                        size="sm"
                                                        variant="outline"
                                                        disabled={disabled}
                                                        onClick={() =>
                                                            patch({
                                                                skill: null,
                                                                instructions: values.skillContext,
                                                                skillContext: '',
                                                            })
                                                        }
                                                    >
                                                        Detach skill
                                                    </Button>
                                                </ItemActions>
                                            </Item>
                                            <LoopFormField
                                                label="Extra context"
                                                htmlFor="loop-form-skill-context"
                                                hint="Optional. Sent to the skill on each run."
                                            >
                                                <Textarea
                                                    id="loop-form-skill-context"
                                                    value={values.skillContext}
                                                    disabled={disabled}
                                                    rows={4}
                                                    onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                                        patch({ skillContext: event.target.value })
                                                    }
                                                />
                                            </LoopFormField>
                                        </>
                                    ) : (
                                        <LoopFormField label="Instructions" htmlFor="loop-form-instructions">
                                            <Textarea
                                                id="loop-form-instructions"
                                                value={values.instructions}
                                                placeholder="Summarize failing CI runs from the last 24 hours and post the summary to #eng-standup."
                                                disabled={disabled}
                                                rows={8}
                                                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                                    patch({ instructions: event.target.value })
                                                }
                                                data-attr="today-space-loop-form-instructions"
                                            />
                                        </LoopFormField>
                                    )}
                                    {workflow && (
                                        <LoopTeamSkillsField
                                            value={values.teamSkills}
                                            disabled={disabled}
                                            onChange={(teamSkills) => patch({ teamSkills })}
                                        />
                                    )}
                                </div>
                            </SpaceSettingsSection>

                            <SpaceSettingsSection
                                label="When"
                                description={
                                    workflow
                                        ? 'Pick a schedule or a GitHub event. Each loop has one trigger.'
                                        : 'Add triggers, or leave none to run the loop only by hand.'
                                }
                            >
                                <SpaceLoopTriggerEditor
                                    triggers={values.triggers}
                                    backend={formBackend}
                                    endpointPath={endpointPath}
                                    disabled={disabled}
                                    onChange={(triggers) => patch({ triggers })}
                                />
                            </SpaceSettingsSection>

                            <SpaceSettingsSection
                                label="Options"
                                description={
                                    workflow
                                        ? 'Where the agent works.'
                                        : 'Who sees the loop, where it works, and who hears about it.'
                                }
                            >
                                <div className="flex flex-col gap-4">
                                    {!workflow && (
                                        <LoopFormField
                                            label="Visibility"
                                            hint={
                                                values.contextTarget
                                                    ? 'A loop in a space is visible to the team.'
                                                    : undefined
                                            }
                                        >
                                            <LoopSelect
                                                value={values.visibility}
                                                options={VISIBILITY_OPTIONS}
                                                onChange={(visibility) => patch({ visibility })}
                                                disabled={disabled || !!values.contextTarget}
                                                ariaLabel="Visibility"
                                                className="w-48"
                                            />
                                        </LoopFormField>
                                    )}
                                    <LoopFormField
                                        label="Repository"
                                        hint={
                                            values.repositories.length > 1
                                                ? `${values.repositories.length - 1} more repositories stay attached.`
                                                : 'Optional for loops that only report.'
                                        }
                                    >
                                        <LoopRepositoryPicker
                                            value={values.repositories[0] ?? null}
                                            disabled={disabled}
                                            onChange={(repository) =>
                                                patch({
                                                    repositories: repository
                                                        ? [repository, ...values.repositories.slice(1)]
                                                        : values.repositories.slice(1),
                                                })
                                            }
                                        />
                                    </LoopFormField>
                                    {!workflow && (
                                        <LoopFormField
                                            label="Sandbox environment"
                                            hint="Its environment variables, network access and image apply to every run."
                                        >
                                            <LoopSelect
                                                value={values.sandboxEnvironmentId ?? DEFAULT_SANDBOX_VALUE}
                                                options={sandboxOptions}
                                                onChange={(next) =>
                                                    patch({
                                                        sandboxEnvironmentId:
                                                            next === DEFAULT_SANDBOX_VALUE ? null : next,
                                                    })
                                                }
                                                disabled={disabled || sandboxEnvironmentsLoading}
                                                ariaLabel="Sandbox environment"
                                            />
                                        </LoopFormField>
                                    )}
                                    <LoopFormField label="Space" hint="The space whose feed shows each run.">
                                        <LoopContextField
                                            value={values.contextTarget}
                                            canvases={spaceCanvases}
                                            showOutputs={!workflow}
                                            disabled={disabled}
                                            onChange={(contextTarget) => patch({ contextTarget, visibility: 'team' })}
                                        />
                                    </LoopFormField>
                                    {!workflow && (
                                        <LoopFormField label="Notifications">
                                            <LoopNotificationsFields
                                                notifications={values.notifications}
                                                disabled={disabled}
                                                onChange={(notifications) => patch({ notifications })}
                                            />
                                        </LoopFormField>
                                    )}
                                </div>
                            </SpaceSettingsSection>

                            <SpaceSettingsSection
                                label="Advanced"
                                description={
                                    workflow ? 'Model and reasoning.' : 'Pull request fixes, model and reasoning.'
                                }
                            >
                                <div className="flex flex-col gap-4">
                                    {!workflow && (
                                        <ItemGroup combined>
                                            <Item variant="outline" size="sm">
                                                <ItemContent>
                                                    <ItemTitle>Auto-fix pull requests</ItemTitle>
                                                    <ItemDescription>
                                                        Watch CI and review comments on pull requests this loop opens,
                                                        and let PostHog push fixes.
                                                    </ItemDescription>
                                                </ItemContent>
                                                <ItemActions>
                                                    <Switch
                                                        size="sm"
                                                        checked={isAutoFixEnabled(values.behaviors)}
                                                        disabled={disabled}
                                                        aria-label="Auto-fix pull requests"
                                                        onCheckedChange={(checked: boolean) =>
                                                            patch({ behaviors: withAutoFix(values.behaviors, checked) })
                                                        }
                                                    />
                                                </ItemActions>
                                            </Item>
                                        </ItemGroup>
                                    )}
                                    <LoopModelFields
                                        values={values}
                                        formBackend={formBackend}
                                        disabled={disabled}
                                        onPatch={patch}
                                    />
                                </div>
                            </SpaceSettingsSection>

                            <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t bg-background py-3">
                                {submitDisabledReason && submitDisabledReason !== 'Saving…' && (
                                    <Text render={<span />} size="xs" variant="muted" className="mr-auto">
                                        {submitDisabledReason}
                                    </Text>
                                )}
                                <Button variant="outline" onClick={cancel} data-attr="today-space-loop-form-cancel">
                                    Cancel
                                </Button>
                                <Tooltip disabled={!submitDisabledReason || submitting}>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="primary"
                                                loading={submitting}
                                                disabled={!!submitDisabledReason && !submitting}
                                                onClick={submit}
                                                data-attr="today-space-loop-form-save"
                                            />
                                        }
                                    >
                                        {isEdit ? 'Save' : 'Create loop'}
                                    </TooltipTrigger>
                                    <TooltipContent>{submitDisabledReason}</TooltipContent>
                                </Tooltip>
                            </div>
                        </>
                    )}
                </div>

                <AlertDialog open={discardOpen} onOpenChange={(open: boolean) => setDiscardOpen(open)}>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Discard your changes?</AlertDialogTitle>
                            <AlertDialogDescription>
                                {isEdit ? 'This loop has changes that aren’t saved.' : 'This new loop isn’t saved yet.'}
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Keep editing</AlertDialogClose>
                            <Button
                                variant="destructive-outline"
                                onClick={leave}
                                data-attr="today-space-loop-form-discard"
                            >
                                Discard
                            </Button>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </SceneContent>
        </TooltipProvider>
    )
}
