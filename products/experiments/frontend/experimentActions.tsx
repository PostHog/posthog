import { type ReactNode } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonCheckbox, LemonDialog } from '@posthog/lemon-ui'
import { Checkbox, Field, Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Label } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { isQuillExperimentsView, openQuillConfirm } from 'scenes/experiments/openQuillConfirm'

import { Experiment } from '~/types'

import {
    hasEnded,
    isExperimentExposureFrozen,
    isExperimentPaused,
    isLaunched,
} from 'products/experiments/frontend/experimentStatus'
import {
    estimateFreezeExposureSeconds,
    formatFreezeExposureDuration,
} from 'products/experiments/frontend/freezeExposureDuration'

/** Whether an experiment is in a state where it can be archived (ignoring permissions). */
export function canArchiveExperiment(
    experiment: Pick<Experiment, 'archived' | 'start_date' | 'end_date' | 'status'>
): boolean {
    return !experiment.archived && hasEnded(experiment)
}

/** Whether the experiment's flag release groups still carry the exposure-freeze stamps.
 * Unlike the status check, this also covers paused or stopped experiments whose flag was
 * frozen earlier — reset clears the stamps in all of those states. */
export function hasFrozenExposureStamps(experiment: Pick<Experiment, 'feature_flag'>): boolean {
    return !!experiment.feature_flag?.filters?.groups?.some((group) => group.exposure_frozen === true)
}

/** Whether an experiment can have its exposure frozen (ignoring permissions). */
export function canFreezeExposure(
    experiment: Pick<Experiment, 'start_date' | 'end_date' | 'status' | 'feature_flag' | 'holdout_id' | 'holdout'>
): boolean {
    const flagFilters = experiment.feature_flag?.filters
    // Freezing exposure narrows the flag to a person cohort, which group-aggregated flags can't use.
    const isGroupAggregated = flagFilters?.aggregation_group_type_index != null
    // Holdout assignment and early access enrollment (super_groups) are evaluated before release
    // conditions, so the freeze couldn't stop enrollment through them — the backend rejects these.
    const hasHoldout =
        experiment.holdout_id != null ||
        experiment.holdout != null ||
        !!flagFilters?.holdout ||
        !!flagFilters?.holdout_groups?.length
    const hasSuperGroups = !!flagFilters?.super_groups?.length
    return (
        isLaunched(experiment) &&
        !hasEnded(experiment) &&
        !isExperimentPaused(experiment) &&
        !isExperimentExposureFrozen(experiment) &&
        !isGroupAggregated &&
        !hasHoldout &&
        !hasSuperGroups
    )
}

function QuillConfirmBody({ children }: { children: ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-2 [&_p]:mb-0">{children}</div>
}

function FreezeExposureCopy(): JSX.Element {
    return (
        <>
            <p>
                New users can <b>no longer enroll</b>. Everyone already enrolled keeps their variant, and metrics keep
                updating — useful for measuring long-term impact (revenue, retention, renewals) after you stop adding
                new users.
            </p>
            <p>
                This snapshots the currently-exposed users into a static cohort and narrows the feature flag to it. The
                experiment <b>keeps running</b>, so results keep updating.
            </p>
            <p>
                From a frozen state you can end an experiment or ship a variant at any time. You can unfreeze as well to
                reopen enrollment.
            </p>
        </>
    )
}

const FREEZE_SLOW_NOTE = 'Freezing can take a little while on projects with many users, so keep this dialog open.'

function freezeDurationTitle(exposedUsers: number): string {
    return `Freezing takes ${formatFreezeExposureDuration(estimateFreezeExposureSeconds(exposedUsers))}`
}

function freezeDurationDetail(exposedUsers: number): string {
    return `${humanFriendlyNumber(exposedUsers)} exposed ${exposedUsers === 1 ? 'user' : 'users'}. Keep this dialog open until it finishes.`
}

/** `exposedUsers` is 0 when the exposure count has not loaded, and the dialog then shows no estimate. */
export function confirmFreezeExposure(onConfirm: () => Promise<void>, exposedUsers: number): void {
    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Freeze exposure?',
            description: (
                <QuillConfirmBody>
                    <FreezeExposureCopy />
                    {exposedUsers > 0 ? (
                        <Item variant="outline" size="sm" tone="info">
                            <ItemMedia variant="icon" aria-hidden>
                                <IconClock />
                            </ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle>{freezeDurationTitle(exposedUsers)}</ItemTitle>
                                <ItemDescription className="line-clamp-none">
                                    {freezeDurationDetail(exposedUsers)}
                                </ItemDescription>
                            </ItemContent>
                        </Item>
                    ) : (
                        <p>{FREEZE_SLOW_NOTE}</p>
                    )}
                </QuillConfirmBody>
            ),
            confirmLabel: 'Freeze exposure',
            awaitConfirm: true,
            onConfirm,
        })
        return
    }
    LemonDialog.open({
        title: 'Freeze exposure?',
        content: (
            <div className="text-sm text-secondary max-w-md">
                <FreezeExposureCopy />
                {exposedUsers > 0 ? (
                    <LemonBanner type="info" icon={<IconClock className="LemonBanner__icon" />}>
                        <div className="font-semibold">{freezeDurationTitle(exposedUsers)}</div>
                        <div className="font-normal">{freezeDurationDetail(exposedUsers)}</div>
                    </LemonBanner>
                ) : (
                    <p>{FREEZE_SLOW_NOTE}</p>
                )}
            </div>
        ),
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Freeze exposure',
            type: 'primary',
            onClick: () => onConfirm(),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

function MoveStartDateCopy({ from, to }: { from: JSX.Element; to: JSX.Element }): JSX.Element {
    return (
        <>
            <p>
                The start date moves from {from} to {to}. The results will leave out the exposures in between.
            </p>
            <p>Your users see no change, and you can move the start date back later.</p>
        </>
    )
}

/** `projectTimezone` is the one the health findings name their dates in, so the dialog shows the same date. */
export function confirmMoveStartDate({
    currentStartDate,
    newStartDate,
    projectTimezone,
    onConfirm,
}: {
    currentStartDate: string
    newStartDate: string
    projectTimezone: string
    onConfirm: () => Promise<void>
}): void {
    const date = (time: string): JSX.Element => (
        <TZLabel time={time} displayTimezone={projectTimezone} formatDate="MMMM D, YYYY [at]" formatTime="h:mm A" />
    )
    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Move the start date?',
            description: (
                <QuillConfirmBody>
                    <MoveStartDateCopy from={date(currentStartDate)} to={date(newStartDate)} />
                </QuillConfirmBody>
            ),
            confirmLabel: 'Move start date',
            awaitConfirm: true,
            onConfirm,
        })
        return
    }
    LemonDialog.open({
        title: 'Move the start date?',
        content: (
            <div className="text-sm text-secondary max-w-md">
                <MoveStartDateCopy from={date(currentStartDate)} to={date(newStartDate)} />
            </div>
        ),
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Move start date',
            type: 'primary',
            onClick: () => onConfirm(),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

function UnfreezeExposureCopy(): JSX.Element {
    return (
        <>
            <p>
                New users can <b>enroll again</b> under the flag's original release conditions. Everyone already
                enrolled keeps their variant, and the snapshot cohort is removed.
            </p>
            <p>
                Heads up: users enrolled before the freeze and after the unfreeze joined at different times, which can
                mix populations and cause bias in your results.
            </p>
            <p>Unfreezing can take a little while on projects with many users, so keep this dialog open.</p>
        </>
    )
}

export function confirmUnfreezeExposure(onConfirm: () => Promise<void>): void {
    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Unfreeze exposure?',
            description: (
                <QuillConfirmBody>
                    <UnfreezeExposureCopy />
                </QuillConfirmBody>
            ),
            confirmLabel: 'Unfreeze exposure',
            awaitConfirm: true,
            onConfirm,
        })
        return
    }
    LemonDialog.open({
        title: 'Unfreeze exposure?',
        content: (
            <div className="text-sm text-secondary max-w-md">
                <UnfreezeExposureCopy />
            </div>
        ),
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Unfreeze exposure',
            type: 'primary',
            onClick: () => onConfirm(),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

const ARCHIVE_EXPERIMENT_COPY =
    'This action will hide the experiment from the list by default. It can be restored at any time.'

function ArchiveFlagLabel({ flagKey }: { flagKey: string | undefined }): JSX.Element {
    return (
        <span>
            Also disable and archive the linked feature flag <code>{flagKey}</code>. It's still enabled — if your code
            still references it, users will fall back to the default. Only do this after removing it from your codebase.
        </span>
    )
}

export function confirmArchiveExperiment(
    experiment: Pick<Experiment, 'feature_flag'>,
    onConfirm: (disableFeatureFlag: boolean) => void
): void {
    // Only an enabled flag needs a decision — a disabled flag is archived automatically.
    const flagIsEnabled = !!experiment.feature_flag?.active
    let disableFeatureFlag = false

    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Archive this experiment?',
            description: (
                <div className="flex flex-col gap-3 [&_p]:mb-0">
                    <p>{ARCHIVE_EXPERIMENT_COPY}</p>
                    {flagIsEnabled && (
                        <Field orientation="horizontal" className="items-start">
                            <Checkbox
                                id="archive-experiment-disable-flag"
                                defaultChecked={false}
                                onCheckedChange={(checked: boolean) => {
                                    disableFeatureFlag = checked
                                }}
                            />
                            <Label htmlFor="archive-experiment-disable-flag" className="font-normal leading-normal">
                                <ArchiveFlagLabel flagKey={experiment.feature_flag?.key} />
                            </Label>
                        </Field>
                    )}
                </div>
            ),
            confirmLabel: 'Archive',
            onConfirm: () => onConfirm(disableFeatureFlag),
        })
        return
    }

    LemonDialog.open({
        title: 'Archive this experiment?',
        content: (
            <div className="flex flex-col gap-3">
                <div className="text-sm text-secondary">{ARCHIVE_EXPERIMENT_COPY}</div>
                {flagIsEnabled && (
                    <LemonCheckbox
                        defaultChecked={false}
                        onChange={(checked) => {
                            disableFeatureFlag = checked
                        }}
                        label={<ArchiveFlagLabel flagKey={experiment.feature_flag?.key} />}
                    />
                )}
            </div>
        ),
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            onClick: () => onConfirm(disableFeatureFlag),
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

function ResetExperimentCopy({ experiment }: { experiment: Pick<Experiment, 'feature_flag'> }): JSX.Element {
    return (
        <>
            <p>The experiment start and end dates will be reset and the experiment will go back to draft mode.</p>
            <p>
                All events collected thus far will still exist, but won't be applied to the experiment unless you
                manually change the start date after launching the experiment again.
            </p>
            {hasFrozenExposureStamps(experiment) ? (
                <p>
                    The <b>exposure freeze is removed</b>: the flag serves its original release conditions again and the
                    snapshot cohort is deleted. Everything else on the flag stays untouched.
                </p>
            ) : (
                <p>
                    The <b>feature flag remains untouched</b>, so variants stay visible to users.
                </p>
            )}
        </>
    )
}

const RESET_UNARCHIVE_NOTE = 'Resetting will also unarchive the experiment.'

export function confirmResetExperiment(
    experiment: Pick<Experiment, 'archived' | 'feature_flag'>,
    onConfirm: () => void
): void {
    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Reset analysis?',
            description: (
                <QuillConfirmBody>
                    <ResetExperimentCopy experiment={experiment} />
                    {experiment.archived && <p>{RESET_UNARCHIVE_NOTE}</p>}
                </QuillConfirmBody>
            ),
            confirmLabel: 'Confirm',
            onConfirm,
        })
        return
    }
    LemonDialog.open({
        title: 'Reset analysis?',
        content: (
            <>
                <div className="text-sm text-secondary max-w-md">
                    <ResetExperimentCopy experiment={experiment} />
                </div>
                {experiment.archived && <div className="text-sm text-secondary">{RESET_UNARCHIVE_NOTE}</div>}
            </>
        ),
        primaryButton: {
            children: 'Confirm',
            type: 'primary',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

const DELETE_EXPERIMENT_COPY = 'Experiment with its settings will be deleted, but event data will be preserved.'

export function confirmDeleteExperiment(opts: {
    projectId: number | null
    experiment: Pick<Experiment, 'id' | 'name'>
    onDelete: () => void
}): void {
    if (!opts.projectId) {
        return
    }
    const projectId = opts.projectId
    const deleteExperiment = (): void => {
        void deleteWithUndo({
            endpoint: `projects/${projectId}/experiments`,
            object: { name: opts.experiment.name, id: opts.experiment.id },
            callback: opts.onDelete,
        })
    }
    if (isQuillExperimentsView()) {
        openQuillConfirm({
            title: 'Delete this experiment?',
            description: DELETE_EXPERIMENT_COPY,
            confirmLabel: 'Delete',
            destructive: true,
            onConfirm: deleteExperiment,
        })
        return
    }
    LemonDialog.open({
        title: 'Delete this experiment?',
        content: <div className="text-sm text-secondary">{DELETE_EXPERIMENT_COPY}</div>,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            onClick: deleteExperiment,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}
