import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { urls } from 'scenes/urls'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount } from '../../utils/credits'
import { type ReplayFiltersCreditCap, replayFiltersScannerLogic } from '../replayFiltersScannerLogic'
import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import type { ReplayScanner } from '../types'
import { eligibleFilterGroups } from './ScannerGoalOverview'

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
    const notKept = [
        'the date range',
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
                    A Replay vision scanner watches new session recordings for you.{' '}
                    {handoff.narrowsSessions
                        ? 'It starts from these filters, and PostHog AI can narrow them to fit what you ask.'
                        : 'With no filters, it starts from every new recording, and PostHog AI can narrow that to fit what you ask.'}
                </div>
            </div>

            <div className="flex flex-col gap-1.5 rounded border border-dashed border-primary p-2">
                <div className="text-xxs font-semibold uppercase text-secondary">Starts from these recordings</div>
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
                    Not kept: {notKept}. The Replay vision scanner starts from now.
                </div>
                {!handoff.narrowsSessions ? (
                    <div className="text-xs text-secondary">
                        To watch only some recordings, close this and add a filter.
                    </div>
                ) : null}
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

            <div className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold">Do you want to set a credit cap for this scanner?</span>
                <LemonSegmentedButton<ReplayFiltersCreditCap>
                    size="small"
                    value={spendChoice.mode === 'free' ? 'free' : 'cap'}
                    onChange={setCreditCap}
                    options={[
                        {
                            value: 'free',
                            label: 'No, use free credits only',
                            disabledReason: spendChoice.freeDisabledReason ?? undefined,
                            'data-attr': 'replay-filters-scanner-spend-free',
                        },
                        { value: 'cap', label: 'Yes, set a cap', 'data-attr': 'replay-filters-scanner-spend-cap' },
                    ]}
                />
                {spendChoice.mode === 'free' ? (
                    <div className="text-xs text-secondary">
                        The Replay vision scanner only uses your free monthly credits
                        {/* Its own span, so page translation cannot strand the changing balance. */}
                        <span>{freeCreditsLeft != null ? ` (${formatCreditCount(freeCreditsLeft)} left)` : ''}</span>.
                        It pauses when they run out, so it never adds to your bill.
                    </div>
                ) : (
                    <LemonInput
                        aria-label="Monthly credit cap"
                        type="number"
                        min={1}
                        value={budget ?? undefined}
                        onChange={(value) => setBudget(value ?? null)}
                        suffix={<span className="text-secondary">credits a month</span>}
                        size="small"
                        className="w-56"
                        data-attr="replay-filters-scanner-budget"
                    />
                )}
            </div>

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
