import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount } from '../../utils/credits'
import { GoalDraftRequest, GoalSpendMode, goalSpendChoice, replayScannerLogic } from '../replayScannerLogic'
import { ScannerGoalExperimentStarter } from './ScannerGoalExperimentStarter'
import { SCANNER_GOAL_STARTERS, ScannerGoalStarter } from './scannerGoalStarters'
import { ScannerResumeDraftBanner } from './ScannerResumeDraftBanner'
import { startScannerFromScratch } from './startScannerFromScratch'

// Credits, not recordings: the agent picks the model, so a fixed recording count no longer maps to
// a fixed cost. The budget is what the user actually controls, and matches how we bill.
const MIN_SCAN_BUDGET = 1
const MAX_SCAN_BUDGET = 100000000

/** The goal-based creation flow: a typed goal and a monthly budget on the left, one-click starting
 * points on the right. Both draft a full scanner through the agent and land the user on the overview
 * step to review it, so a one-click start still gets a scanner fitted to the project. */
export function ScannerGoalFlow(): JSX.Element {
    const logic = replayScannerLogic({ id: 'new' })
    const { goalDraftInput, goalBudgetInput, goalSpendMode, goalDraftLoading, linkedExperimentContext } =
        useValues(logic)
    const { draftScannerFromGoal, setGoalDraftInput, setGoalBudgetInput, setGoalSpendMode } = useActions(logic)
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
    const startDisabledReason =
        editDisabledReason ??
        (!budgetValid ? 'Enter a monthly credit budget' : goalDraftLoading ? 'Drafting your scanner' : null)

    const typedGoalDisabledReason =
        startDisabledReason ?? (!goalDraftInput.trim() ? 'Describe what you want to find out' : null)

    const start = (goal: string, templateKey?: string, experimentId?: number): void => {
        if (!spendChoice.spend) {
            return
        }
        const request: GoalDraftRequest = { goal, spend: spendChoice.spend, templateKey, experimentId }
        // Drafting calls an AI endpoint the backend rejects without org consent; interpose the
        // popover instead of letting the request 400.
        if (!dataProcessingAccepted) {
            setPendingDraft(request)
            return
        }
        draftScannerFromGoal(request)
    }
    const startFromTypedGoal = (): void => {
        if (!typedGoalDisabledReason) {
            start(goalDraftInput.trim())
        }
    }
    const startFromStarter = (starter: ScannerGoalStarter): void => {
        if (!startDisabledReason) {
            start(starter.goal, starter.key)
        }
    }

    return (
        <div className="@container flex flex-col gap-4">
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
                <div className="grid grid-cols-1 @3xl:grid-cols-2 gap-4">
                    <div className="rounded-lg border-2 border-[var(--color-ai)] p-4 flex flex-col gap-4">
                        <div className="flex flex-col gap-1">
                            <label htmlFor="vision-goal-flow-goal" className="text-sm font-semibold">
                                Which sessions should the scanner watch for you and what should it find out?
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
                                Say what to learn and which part of the product to watch. The agent maps it onto your
                                real pages.
                            </div>
                            {/* A draft restored from an earlier experiment-scoped session keeps its targeting
                                through this flow, so say whose sessions the scanner ends up watching. */}
                            {linkedExperimentContext ? (
                                <div className="text-xs text-muted">
                                    This scanner keeps watching people exposed to{' '}
                                    {linkedExperimentContext.experiment.name}. You don't have to mention the experiment.
                                </div>
                            ) : null}
                        </div>

                        <div className="flex flex-col gap-2">
                            <span className="text-sm font-semibold">How much should this scanner use?</span>
                            {/* The card sits inside the consent popover's reference, which would give these buttons dropdown arrows. */}
                            <PopoverReferenceContext.Provider value={null}>
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
                            </PopoverReferenceContext.Provider>
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

                        <div className="flex items-center justify-between mt-auto">
                            <div className="flex items-center gap-1.5 text-xs text-tertiary">
                                <IconSparkles className="text-ai size-3.5" />
                                <span>PostHog AI</span>
                            </div>
                            <LemonButton
                                type="primary"
                                loading={goalDraftLoading}
                                // Inside the consent popover's reference, so Lemon would add a dropdown chevron.
                                sideIcon={null}
                                disabledReason={typedGoalDisabledReason}
                                onClick={startFromTypedGoal}
                                data-attr="vision-goal-flow-submit"
                            >
                                Draft my scanner
                            </LemonButton>
                        </div>
                    </div>

                    <div className="rounded-lg border border-border bg-bg-light p-4 flex flex-col gap-2">
                        <span className="text-sm font-semibold">Common starting points</span>
                        <span className="text-xs text-muted">One click drafts a scanner fitted to your project.</span>
                        <div className="flex flex-col gap-1">
                            {SCANNER_GOAL_STARTERS.map((starter) => (
                                <LemonButton
                                    key={starter.key}
                                    fullWidth
                                    icon={starter.icon}
                                    sideIcon={<IconChevronRight />}
                                    tooltip={starter.goal}
                                    disabledReason={startDisabledReason}
                                    onClick={() => startFromStarter(starter)}
                                    data-attr={`vision-goal-starter-${starter.key}`}
                                >
                                    {starter.question}
                                </LemonButton>
                            ))}
                            {/* Inside the consent popover's reference, which would give its buttons dropdown arrows. */}
                            <PopoverReferenceContext.Provider value={null}>
                                <ScannerGoalExperimentStarter
                                    disabledReason={startDisabledReason}
                                    onDraft={(goal, experimentId) => start(goal, 'track_experiment', experimentId)}
                                />
                            </PopoverReferenceContext.Provider>
                        </div>
                    </div>
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
