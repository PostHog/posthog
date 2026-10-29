import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonTextArea, Link } from '@posthog/lemon-ui'

import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { GoalDraftRequest, GoalSpendMode, goalSpendChoice, replayScannerLogic } from '../replayScannerLogic'
import { ScannerGoalExperimentStarter } from './ScannerGoalExperimentStarter'
import { SCANNER_GOAL_STARTERS } from './scannerGoalStarters'
import { ScannerResumeDraftBanner } from './ScannerResumeDraftBanner'
import { startScannerFromScratch } from './startScannerFromScratch'

// Credits, not recordings: the agent picks the model, so a fixed recording count no longer maps to
// a fixed cost. The budget is what the user actually controls, and matches how we bill.
const MIN_SCAN_BUDGET = 1
const MAX_SCAN_BUDGET = 100000000

const experimentGoal = (experiment: ExperimentBasicApi): string =>
    `Track how users experience the "${experiment.name}" experiment`

/** The goal-based creation flow: one goal box, starters that fill it, a monthly budget, and a single
 * button that drafts the scanner through the agent and lands the user on the overview step to review it. */
export function ScannerGoalFlow(): JSX.Element {
    const logic = replayScannerLogic({ id: 'new' })
    const {
        goalDraftInput,
        goalBudgetInput,
        goalSpendMode,
        goalDraftLoading,
        goalExperiment: experiment,
        linkedExperimentContext,
        goalDraftQuery,
    } = useValues(logic)
    const {
        draftScannerFromGoal,
        setGoalDraftInput,
        setGoalBudgetInput,
        setGoalSpendMode,
        setGoalExperiment,
        setGoalDraftQuery,
    } = useActions(logic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { freeCreditsLeft } = useValues(visionQuotaLogic)
    // The spend choice is captured with the goal, so a quota that loads while consent is open cannot change it.
    const [pendingDraft, setPendingDraft] = useState<GoalDraftRequest | null>(null)

    // Drafting creates a scanner, so it needs the same editor access as the rest of the wizard.
    const editDisabledReason = getReplayVisionEditDisabledReason()
    const spendChoice = goalSpendChoice(goalSpendMode, goalBudgetInput, freeCreditsLeft)
    const spendMode = spendChoice.mode
    const budgetValid =
        spendMode === 'free' ||
        (goalBudgetInput != null && goalBudgetInput >= MIN_SCAN_BUDGET && goalBudgetInput <= MAX_SCAN_BUDGET)
    const starterDisabledReason = editDisabledReason ?? (goalDraftLoading ? 'Drafting your scanner' : null)
    // The server refuses an experiment other than the one the replay filters already scope to.
    const experimentStarterDisabledReason =
        starterDisabledReason ??
        (goalDraftQuery?.experiment_exposure ? 'Your replay filters already pick an experiment' : null)
    const submitDisabledReason =
        starterDisabledReason ??
        (!goalDraftInput.trim()
            ? 'Describe what you want to find out'
            : !budgetValid
              ? 'Enter a monthly credit budget'
              : null)
    // A starter counts only while its goal is unedited, so the funnel can split typed goals from starter ones.
    const activeStarter = SCANNER_GOAL_STARTERS.find((starter) => starter.goal === goalDraftInput.trim())

    const changeExperiment = (picked: ExperimentBasicApi | null): void => {
        if (picked) {
            setGoalDraftInput(experimentGoal(picked))
        } else if (experiment && goalDraftInput.trim() === experimentGoal(experiment)) {
            setGoalDraftInput('')
        }
        setGoalExperiment(picked)
    }
    const submit = (): void => {
        const goal = goalDraftInput.trim()
        if (submitDisabledReason || !spendChoice.spend) {
            return
        }
        const request: GoalDraftRequest = {
            goal,
            spend: spendChoice.spend,
            templateKey: experiment ? 'track_experiment' : activeStarter?.key,
            experimentId: experiment?.id,
        }
        // Drafting calls an AI endpoint the backend rejects without org consent; interpose the
        // popover instead of letting the request 400.
        if (!dataProcessingAccepted) {
            setPendingDraft(request)
            return
        }
        draftScannerFromGoal(request)
    }

    return (
        <div className="flex flex-col gap-4 w-full max-w-3xl mx-auto">
            <ScannerResumeDraftBanner />
            <AIConsentPopoverWrapper
                placement="bottom"
                showArrow
                ignoreDismissal
                hideTrainingDisclaimer
                hidden={pendingDraft === null}
                onApprove={() => {
                    if (pendingDraft) {
                        draftScannerFromGoal(pendingDraft)
                    }
                    setPendingDraft(null)
                }}
                onDismiss={() => setPendingDraft(null)}
            >
                <div className="rounded-lg border-2 border-[var(--color-ai)] p-4 flex flex-col gap-4">
                    {/* The card is the consent popover's reference, which would give its buttons dropdown arrows. */}
                    <PopoverReferenceContext.Provider value={null}>
                        <div className="flex flex-col gap-1">
                            <label htmlFor="vision-goal-flow-goal" className="text-sm font-semibold">
                                Describe your goal
                            </label>
                            <LemonTextArea
                                id="vision-goal-flow-goal"
                                value={goalDraftInput}
                                onChange={setGoalDraftInput}
                                placeholder="e.g. Watch users who enter the checkout flow and summarize why customers convert or drop off"
                                minRows={3}
                                maxRows={6}
                                data-attr="vision-goal-flow-goal"
                            />
                            <div className="text-xs text-muted">
                                Say which sessions to watch and what to learn from them. The agent maps it onto your
                                real pages.
                            </div>
                            {/* A draft restored from an earlier experiment-scoped session keeps its targeting
                            through this flow, so say whose sessions the scanner ends up watching. */}
                            {linkedExperimentContext && !experiment ? (
                                <div className="text-xs text-muted">
                                    This scanner keeps watching users exposed to{' '}
                                    {linkedExperimentContext.experiment.name}. You don't have to mention the experiment.
                                </div>
                            ) : null}
                            {goalDraftQuery ? (
                                <div className="text-xs text-muted">
                                    This scanner starts from the replay filters you picked. The agent can narrow them,
                                    but not widen them.{' '}
                                    <Link
                                        onClick={() => setGoalDraftQuery(null)}
                                        data-attr="vision-goal-flow-clear-query"
                                    >
                                        Let the agent pick the recordings instead
                                    </Link>
                                </div>
                            ) : null}
                        </div>

                        <div className="flex flex-col gap-2">
                            <span className="text-sm font-semibold">Or start from a common question</span>
                            <div className="flex flex-wrap gap-2">
                                {SCANNER_GOAL_STARTERS.map((starter) => (
                                    <LemonButton
                                        key={starter.key}
                                        type="secondary"
                                        size="xsmall"
                                        icon={starter.icon}
                                        active={!experiment && activeStarter?.key === starter.key}
                                        disabledReason={starterDisabledReason}
                                        onClick={() => {
                                            setGoalExperiment(null)
                                            setGoalDraftInput(starter.goal)
                                        }}
                                        data-attr={`vision-goal-starter-${starter.key}`}
                                    >
                                        {starter.question}
                                    </LemonButton>
                                ))}
                                <ScannerGoalExperimentStarter
                                    experiment={experiment}
                                    disabledReason={experimentStarterDisabledReason}
                                    onChange={changeExperiment}
                                />
                            </div>
                        </div>

                        <div className="flex flex-col gap-2">
                            <span className="text-sm font-semibold">How much should this scanner use?</span>
                            <LemonSegmentedButton<GoalSpendMode>
                                size="small"
                                value={spendMode}
                                onChange={setGoalSpendMode}
                                options={[
                                    {
                                        value: 'free',
                                        label: 'Free',
                                        disabledReason: spendChoice.freeDisabledReason ?? undefined,
                                        'data-attr': 'vision-goal-flow-spend-free',
                                    },
                                    {
                                        value: 'budget',
                                        label: 'Set a budget',
                                        'data-attr': 'vision-goal-flow-spend-budget',
                                    },
                                ]}
                            />
                            {spendMode === 'free' ? (
                                <div className="text-xs text-muted">
                                    The scanner only uses your free monthly credits
                                    {/* Its own span, so page translation cannot strand the changing balance. */}
                                    <span>
                                        {freeCreditsLeft != null ? ` (${formatCreditCount(freeCreditsLeft)} left)` : ''}
                                    </span>
                                    . It pauses when they run out, so it never adds to your bill.
                                </div>
                            ) : (
                                <>
                                    <div className="flex flex-wrap items-center gap-3">
                                        <LemonInput
                                            id="vision-goal-flow-budget"
                                            aria-label="Monthly credit budget"
                                            type="number"
                                            min={MIN_SCAN_BUDGET}
                                            max={MAX_SCAN_BUDGET}
                                            value={goalBudgetInput ?? undefined}
                                            onChange={(value) => setGoalBudgetInput(value ?? null)}
                                            suffix={<span className="text-muted">credits a month</span>}
                                            className="w-48"
                                            data-attr="vision-goal-flow-budget"
                                        />
                                        {budgetValid && goalBudgetInput != null ? (
                                            <span className="text-xs text-muted">
                                                ≈ {creditsToUsd(goalBudgetInput)} a month
                                            </span>
                                        ) : null}
                                    </div>
                                    <div className="text-xs text-muted">
                                        1,000 credits ≈ $10. The agent picks the model and fits the scanner to this.
                                    </div>
                                </>
                            )}
                        </div>

                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-xs text-tertiary">
                                <IconSparkles className="text-ai size-3.5" />
                                <span>PostHog AI</span>
                            </div>
                            <LemonButton
                                type="primary"
                                loading={goalDraftLoading}
                                disabledReason={submitDisabledReason}
                                onClick={submit}
                                data-attr="vision-goal-flow-submit"
                            >
                                Draft my scanner
                            </LemonButton>
                        </div>
                    </PopoverReferenceContext.Provider>
                </div>
            </AIConsentPopoverWrapper>

            <div className="flex items-center gap-4">
                <div className="flex-1 border-t border-border" />
                <span className="text-xs text-tertiary uppercase tracking-wide">or</span>
                <div className="flex-1 border-t border-border" />
            </div>

            <div className="flex justify-center">
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={startScannerFromScratch}
                    data-attr="vision-template-blank"
                >
                    Create from scratch
                </LemonButton>
            </div>
        </div>
    )
}
