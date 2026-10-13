import { IconArrowLeft, IconMinus, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ScoutRubricDocumentApi, ScoutTrialSetupApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutTrialsViewProps } from './ScoutTrialsView'
import { MAX_TRIAL_REPEATS, MAX_TRIAL_VARIANTS } from './scoutTrialUtils'
import { ScoutTrialVariantEditor } from './ScoutTrialVariantEditor'

export type ScoutTrialSetupProps = Pick<
    ScoutTrialsViewProps,
    | 'variants'
    | 'repeats'
    | 'note'
    | 'batch'
    | 'submitting'
    | 'totalRuns'
    | 'formError'
    | 'trialsDisabledReason'
    | 'hasUnaccepted'
    | 'updateVariant'
    | 'addVariant'
    | 'removeVariant'
    | 'setRepeats'
    | 'setNote'
    | 'submitComparison'
> & {
    setup: ScoutTrialSetupApi
    rubric: ScoutRubricDocumentApi | null
    rubricLoading: boolean
    rubricError: string | null
    onViewRubric: () => void
    onReloadRubric: () => void
    onBack: () => void
}

export function ScoutTrialSetup(props: ScoutTrialSetupProps): JSX.Element {
    const { setup, variants, repeats, totalRuns, note, rubric, rubricLoading, rubricError, submitting, batch } = props
    const locked = submitting || !!batch
    const lockedReason = locked ? 'Start a new trial to change these settings.' : undefined
    const savedRubric = rubric && rubric.revision > 0
    const enabledChecks = rubric?.criteria.filter((criterion) => criterion.enabled).length ?? 0
    const reference = rubric?.reference_context
    const rubricLabel = savedRubric ? `${enabledChecks} checks · revision ${rubric.revision}` : 'No saved rubric'
    const rubricDisabledReason = rubricLoading
        ? 'Wait for the saved rubric to load.'
        : rubricError
          ? 'Reload the saved rubric first.'
          : !savedRubric
            ? 'Review and save this scout’s rubric first.'
            : !reference
              ? 'Save the rubric with its captured scout reference first.'
              : reference.instructions_truncated ||
                  reference.reference_files_truncated ||
                  reference.reference_limits.omitted_files > 0 ||
                  reference.reference_limits.truncated_files.length > 0
                ? 'Save a complete scout reference before starting a trial.'
                : enabledChecks === 0
                  ? 'Enable at least one rubric check before starting a trial.'
                  : undefined

    return (
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
            <div className="flex flex-col items-start gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    noPadding
                    icon={<IconArrowLeft />}
                    onClick={props.onBack}
                    disabledReason={submitting ? 'Wait for the trial to start.' : undefined}
                    data-attr="scout-trial-back"
                >
                    All trials
                </LemonButton>
                <h2 className="m-0 text-lg font-semibold">New trial</h2>
                <p className="m-0 text-sm text-secondary">Your live scout doesn't change. Trials run on copies.</p>
            </div>

            <LemonCard hoverEffect={false} className="p-4">
                {rubricLoading ? (
                    <LemonSkeleton className="h-12" />
                ) : rubricError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Retry', onClick: props.onReloadRubric, loading: rubricLoading }}
                    >
                        {rubricError}
                    </LemonBanner>
                ) : (
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0 flex-1 basis-80">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                                <span className="font-semibold">
                                    {savedRubric ? 'Graded with the saved rubric' : 'Save a rubric before starting'}
                                </span>
                                <span className="text-secondary">{rubricLabel}</span>
                            </div>
                            <p className="mb-0 mt-1 text-sm text-secondary">
                                Every version is graded against the same rubric. Later rubric edits only apply to new
                                trials.
                            </p>
                        </div>
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={props.onViewRubric}
                            data-attr="scout-trial-view-rubric"
                        >
                            View rubric
                        </LemonButton>
                    </div>
                )}
            </LemonCard>

            <section className="flex min-w-0 flex-col gap-3" aria-label="Versions">
                <h3 className="m-0 text-sm font-semibold">Versions</h3>
                {variants.map((variant, index) => (
                    <ScoutTrialVariantEditor
                        key={variant.id}
                        variant={variant}
                        index={index}
                        setup={setup}
                        locked={locked}
                        removable={variants.length > 2 && index > 0}
                        update={(update) => props.updateVariant(variant.id, update)}
                        remove={() => props.removeVariant(variant.id)}
                    />
                ))}
                <div>
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={props.addVariant}
                        disabledReason={
                            lockedReason ||
                            (variants.length >= MAX_TRIAL_VARIANTS
                                ? `Use up to ${MAX_TRIAL_VARIANTS} versions per trial.`
                                : undefined)
                        }
                        data-attr="scout-trial-add-version"
                    >
                        Add version
                    </LemonButton>
                </div>
            </section>

            <LemonField.Pure
                label="Instructions for every run"
                htmlFor="scout-trial-instructions"
                showOptional
                help="Added to every version. Guides the scout but doesn't limit which data it can access."
            >
                <LemonTextArea
                    id="scout-trial-instructions"
                    value={note}
                    onChange={props.setNote}
                    maxLength={1000}
                    minRows={2}
                    maxRows={6}
                    disabled={locked}
                    placeholder="e.g. Focus on the last 7 days."
                    data-attr="scout-trial-instructions"
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Runs per version"
                htmlFor="scout-trial-repeats"
                help={`More runs make the result more reliable. Up to ${MAX_TRIAL_REPEATS} runs per version.`}
            >
                <div className="flex flex-wrap items-center gap-3">
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type="secondary"
                            icon={<IconMinus />}
                            aria-label="Fewer runs per version"
                            onClick={() => props.setRepeats(repeats - 1)}
                            disabledReason={
                                lockedReason || (repeats <= 1 ? 'Use at least one run per version.' : undefined)
                            }
                            data-attr="scout-trial-fewer-runs"
                        />
                        <LemonInput
                            id="scout-trial-repeats"
                            className="w-20"
                            type="number"
                            value={repeats}
                            min={1}
                            max={MAX_TRIAL_REPEATS}
                            step={1}
                            onChange={(value) => props.setRepeats(value ?? 1)}
                            disabledReason={lockedReason}
                            data-attr="scout-trial-runs-per-version"
                        />
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            aria-label="More runs per version"
                            onClick={() => props.setRepeats(repeats + 1)}
                            disabledReason={
                                lockedReason ||
                                (repeats >= MAX_TRIAL_REPEATS
                                    ? `Use up to ${MAX_TRIAL_REPEATS} runs per version.`
                                    : undefined)
                            }
                            data-attr="scout-trial-more-runs"
                        />
                    </div>
                    <span className="text-sm text-secondary">{`× ${variants.length} versions = ${totalRuns} runs`}</span>
                </div>
            </LemonField.Pure>

            <LemonCard hoverEffect={false} className="flex flex-wrap items-center justify-between gap-4 p-4">
                <div className="min-w-0 flex-1 basis-80">
                    <p className="m-0 flex flex-wrap gap-x-2 gap-y-1 text-sm">
                        <strong>{`${variants.length} versions × ${repeats} runs = ${totalRuns} runs`}</strong>
                        {savedRubric && (
                            <span className="text-secondary">{`· graded with rubric revision ${rubric.revision}`}</span>
                        )}
                    </p>
                    <p className="mb-0 mt-1 text-xs text-secondary">
                        Keeps running after you close this page. Runs and judging use model credits.
                    </p>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        noPadding
                        className="mt-1"
                        data-attr="scout-trial-how-it-works"
                        tooltip={
                            <div className="flex max-w-sm flex-col gap-2 text-sm">
                                <p className="m-0">Every run starts from the same saved history.</p>
                                <p className="m-0">
                                    New reports and memory stay inside the trial. Your live scout doesn't change.
                                </p>
                                <p className="m-0">Project data is live, so it can change while the trial runs.</p>
                            </div>
                        }
                    >
                        How trials work
                    </LemonButton>
                </div>
                {(!batch || props.hasUnaccepted) && (
                    <LemonButton
                        type="primary"
                        size="large"
                        onClick={props.submitComparison}
                        loading={submitting}
                        disabledReason={
                            props.trialsDisabledReason || (batch ? undefined : rubricDisabledReason || props.formError)
                        }
                        data-attr="scout-comparison-start"
                    >
                        {batch ? 'Retry starting trial' : 'Start trial'}
                    </LemonButton>
                )}
            </LemonCard>
        </div>
    )
}
