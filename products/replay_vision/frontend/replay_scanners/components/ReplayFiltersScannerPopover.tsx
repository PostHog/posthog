import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import type { ReplayScanner } from '../types'
import { eligibleFilterGroups } from './ScannerGoalOverview'
import { ScannerSpendChoiceFields } from './ScannerSpendChoiceFields'

const GOAL_PLACEHOLDER =
    'For example: Where do people give up before they pay?\nOr: Watch for errors and buttons that do nothing on the payment step.'

export function ReplayFiltersScannerPopover({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    const { goal, budget, spendChoice, freeCreditsLeft, draftInputDisabledReason, consentSpend } =
        useValues(replayFiltersScannerLogic)
    const {
        setGoal,
        setCreditCap,
        setBudget,
        draftWithAi,
        setUpManually,
        requestConsent,
        confirmConsent,
        cancelConsent,
    } = useActions(replayFiltersScannerLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)

    const editDisabledReason = getReplayVisionEditDisabledReason()
    const draftDisabledReason = editDisabledReason ?? draftInputDisabledReason

    const filterGroups = handoff.narrowsSessions
        ? eligibleFilterGroups({
              query: handoff.query,
              scanner_config: {},
              experiment_targeting: handoff.experiment
                  ? { experiment_id: handoff.experiment.experimentId, variant: handoff.experiment.variantKey }
                  : null,
          } as unknown as ReplayScanner)
        : []
    // The date range is never kept either, but "new recordings only" already says so.
    const notKept = [
        ...(handoff.pinnedSessionCount > 0 ? [pluralize(handoff.pinnedSessionCount, 'pinned recording')] : []),
        ...(handoff.droppedCommentSearch ? ['the comment search'] : []),
    ].join(', ')

    const draft = (): void => {
        if (dataProcessingAccepted) {
            draftWithAi(handoff)
        } else if (spendChoice.spend) {
            requestConsent(spendChoice.spend)
        }
    }

    return (
        <div className="flex flex-col gap-3 p-1 w-[26rem] max-w-full">
            <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1.5 font-semibold">
                    <IconSparkles className="text-ai" />
                    {handoff.narrowsSessions
                        ? 'Create a Replay vision scanner from these filters'
                        : 'Create a Replay vision scanner'}
                </div>
                <div className="text-xs text-secondary">
                    A Replay vision scanner watches new session recordings for you.
                </div>
            </div>

            <div className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold">Which recordings it watches</span>
                <div className="flex flex-wrap gap-1">
                    {filterGroups.length > 0 ? (
                        filterGroups.flatMap((group) =>
                            group.values.map((value) => (
                                <LemonTag key={`${group.key}:${value}`} type="default">
                                    {group.label}: {value}
                                </LemonTag>
                            ))
                        )
                    ) : (
                        // Some filters (custom durations, console logs) have no chip, so only claim "all" when nothing narrows.
                        <LemonTag type="default">
                            {handoff.narrowsSessions ? 'The replay filters you picked' : 'All new session recordings'}
                        </LemonTag>
                    )}
                </div>
                <div className="text-xs text-secondary">
                    New recordings only. PostHog AI can narrow them to fit your goal.
                    {notKept ? <span> Not kept: {notKept}.</span> : null}
                </div>
            </div>

            <div className="flex flex-col gap-1">
                <label htmlFor="replay-filters-scanner-goal" className="text-sm font-semibold">
                    What should it watch for or answer?
                </label>
                <LemonTextArea
                    id="replay-filters-scanner-goal"
                    value={goal}
                    onChange={setGoal}
                    placeholder={GOAL_PLACEHOLDER}
                    minRows={3}
                    maxRows={6}
                    autoFocus
                    data-attr="replay-filters-scanner-goal"
                />
            </div>

            <ScannerSpendChoiceFields
                spendChoice={spendChoice}
                freeCreditsLeft={freeCreditsLeft}
                budget={budget}
                onCreditCapChange={setCreditCap}
                onBudgetChange={setBudget}
                dataAttrPrefix="replay-filters-scanner"
            />

            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    type="tertiary"
                    size="small"
                    disabledReason={editDisabledReason}
                    onClick={() => setUpManually(handoff)}
                    data-attr="replay-filters-scanner-manual"
                >
                    Set up manually
                </LemonButton>
                <AIConsentPopoverWrapper
                    placement="bottom-end"
                    showArrow
                    ignoreDismissal
                    hideTrainingDisclaimer
                    pendingRedirectUrl={urls.replayVisionNewScanner()}
                    hidden={!consentSpend}
                    onBeforeApprove={() => consentSpend && confirmConsent(handoff, consentSpend)}
                    onApprove={() => draftWithAi(handoff, consentSpend ?? undefined)}
                    onDismiss={cancelConsent}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconSparkles />}
                        // Inside the consent popover's reference, so Lemon would add a dropdown chevron.
                        sideIcon={null}
                        disabledReason={draftDisabledReason}
                        onClick={draft}
                        data-attr="replay-filters-scanner-draft"
                    >
                        Draft with AI
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </div>
            <div className="text-xs font-semibold">You can review the draft before the scanner is created.</div>
        </div>
    )
}
