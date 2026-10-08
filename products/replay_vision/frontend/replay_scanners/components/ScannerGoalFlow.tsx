import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerTemplate, defaultScannerTemplates } from '../scannerTemplates'
import { ScannerResumeDraftBanner } from './ScannerResumeDraftBanner'
import { SCANNER_TEMPLATE_ICONS } from './scannerTemplateIcons'
import { startScannerFromTemplate } from './startScannerFromTemplate'

// Credits, not recordings: the agent picks the model, so a fixed recording count no longer maps to
// a fixed cost. The budget is what the user actually controls, and matches how we bill.
const MIN_SCAN_BUDGET = 1
const MAX_SCAN_BUDGET = 100000000

/** The goal-based creation flow: a typed goal and a monthly budget on the left, one-click starting
 * points on the right. Both draft a full scanner through the agent and land the user on the overview
 * step to review it, so a one-click start still gets a scanner fitted to the project. */
export function ScannerGoalFlow(): JSX.Element {
    const logic = replayScannerLogic({ id: 'new' })
    const { goalDraftInput, goalBudgetInput, goalDraftLoading, experimentContext } = useValues(logic)
    const { draftScannerFromGoal, setGoalDraftInput, setGoalBudgetInput } = useActions(logic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [pendingDraft, setPendingDraft] = useState<{ goal: string; templateKey?: string } | null>(null)

    // Drafting creates a scanner, so it needs the same editor access as the rest of the wizard.
    const editDisabledReason = getReplayVisionEditDisabledReason()
    const budgetValid =
        goalBudgetInput != null && goalBudgetInput >= MIN_SCAN_BUDGET && goalBudgetInput <= MAX_SCAN_BUDGET
    const startDisabledReason =
        editDisabledReason ??
        (!budgetValid ? 'Enter a monthly credit budget' : goalDraftLoading ? 'Drafting your scanner' : null)

    const typedGoalDisabledReason =
        startDisabledReason ?? (!goalDraftInput.trim() ? 'Describe what you want to find out' : null)

    const start = (goal: string, templateKey?: string): void => {
        // Drafting calls an AI endpoint the backend rejects without org consent; interpose the
        // popover instead of letting the request 400.
        if (!dataProcessingAccepted) {
            setPendingDraft({ goal, templateKey })
            return
        }
        draftScannerFromGoal(goal, goalBudgetInput ?? undefined, templateKey)
    }
    const startFromTypedGoal = (): void => {
        if (!typedGoalDisabledReason) {
            start(goalDraftInput.trim())
        }
    }
    const startFromStarter = (starter: ScannerTemplate): void => {
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
                        draftScannerFromGoal(pendingDraft.goal, goalBudgetInput ?? undefined, pendingDraft.templateKey)
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
                            {experimentContext ? (
                                <div className="text-xs text-muted">
                                    This scanner keeps watching people exposed to {experimentContext.experiment.name}.
                                    You don't have to mention the experiment.
                                </div>
                            ) : null}
                        </div>

                        <div className="flex flex-col gap-1">
                            <label htmlFor="vision-goal-flow-budget" className="text-sm font-semibold">
                                About how much do you want to spend a month?
                            </label>
                            <div className="flex flex-wrap items-center gap-3">
                                <LemonInput
                                    id="vision-goal-flow-budget"
                                    type="number"
                                    min={MIN_SCAN_BUDGET}
                                    max={MAX_SCAN_BUDGET}
                                    value={goalBudgetInput ?? undefined}
                                    onChange={(value) => setGoalBudgetInput(value ?? null)}
                                    suffix={<span className="text-muted">credits</span>}
                                    className="w-40"
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
                            {defaultScannerTemplates.map((template) => (
                                <LemonButton
                                    key={template.key}
                                    fullWidth
                                    icon={SCANNER_TEMPLATE_ICONS[template.icon]}
                                    sideIcon={<IconChevronRight />}
                                    tooltip={template.goal}
                                    disabledReason={startDisabledReason}
                                    onClick={() => startFromStarter(template)}
                                    data-attr={`vision-goal-starter-${template.key}`}
                                >
                                    {template.goal_question}
                                </LemonButton>
                            ))}
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
                    onClick={() => startScannerFromTemplate(null)}
                    data-attr="vision-template-blank"
                >
                    Create from scratch
                </LemonButton>
            </div>
        </div>
    )
}
