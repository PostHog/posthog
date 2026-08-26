import { useActions, useValues } from 'kea'

import { IconPlus, IconRocket, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import {
    Button,
    ButtonGroup,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { GitHubBranchCombobox } from 'lib/integrations/GitHubBranchCombobox'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { inboxUsageLogic } from '../../logics/inboxUsageLogic'
import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { PRIORITY_THRESHOLD_OPTIONS, SignalReportPriority } from '../../types'

/** Compact segmented-control label per priority. P4 (the lowest bar) reads as "All". */
const THRESHOLD_SEGMENT_LABELS: Record<SignalReportPriority, string> = {
    P0: 'P0',
    P1: 'P1+',
    P2: 'P2+',
    P3: 'P3+',
    P4: 'All',
}
/** Segments derived from the shared priority list, so the value set and order stay single-sourced. */
const THRESHOLD_SEGMENTS = PRIORITY_THRESHOLD_OPTIONS.map(({ value }) => ({
    value,
    label: THRESHOLD_SEGMENT_LABELS[value],
}))

const MY_THRESHOLD_DEFAULT_VALUE = '__default__'
const MY_THRESHOLD_SEGMENTS = [{ value: MY_THRESHOLD_DEFAULT_VALUE, label: 'Default' }, ...THRESHOLD_SEGMENTS]

function BaseBranchOverrideRows(): JSX.Element | null {
    const { baseBranchOverrides, teamConfigUpdating } = useValues(signalTeamConfigLogic)
    const { updateBaseBranchOverride, removeBaseBranchOverride } = useActions(signalTeamConfigLogic)
    const { githubIntegrations } = useValues(integrationsLogic)

    if (baseBranchOverrides.length === 0) {
        return null
    }

    // A stored override is just `org/repo`, so the owning integration has to be recovered from the owner
    // half. A GitHub integration's display name is the installation's account login, which is that owner.
    const integrationsByOwner = new Map(
        githubIntegrations.map((integration) => [integration.display_name.toLowerCase(), integration])
    )

    return (
        <div className="flex flex-col gap-1">
            {baseBranchOverrides.map(({ repo, branch }) => {
                const integration = integrationsByOwner.get(repo.split('/')[0])
                return (
                    <div key={repo} className="flex items-center gap-1">
                        <span className="text-xs text-default min-w-0 flex-1 truncate" title={repo}>
                            {repo}
                        </span>
                        {integration ? (
                            <GitHubBranchCombobox
                                integrationId={integration.id}
                                repo={repo}
                                value={branch}
                                allowCustomValues={false}
                                disabled={teamConfigUpdating}
                                onChange={(next) => {
                                    if (next) {
                                        updateBaseBranchOverride(repo, next)
                                    }
                                }}
                            />
                        ) : (
                            <span className="text-xs text-muted shrink-0">{branch}</span>
                        )}
                        <Button
                            variant="outline"
                            size="sm"
                            loading={teamConfigUpdating}
                            aria-label={`Remove base branch override for ${repo}`}
                            onClick={() => removeBaseBranchOverride(repo)}
                        >
                            <IconX />
                        </Button>
                    </div>
                )
            })}
        </div>
    )
}

function BaseBranchOverridePicker(): JSX.Element {
    const {
        draftBaseBranchIntegrationId,
        draftBaseBranchRepo,
        draftBaseBranchBranch,
        addBaseBranchOverrideDisabledReason,
        teamConfigUpdating,
    } = useValues(signalTeamConfigLogic)
    const { setDraftBaseBranchIntegrationId, setDraftBaseBranchRepo, setDraftBaseBranchBranch, addBaseBranchOverride } =
        useActions(signalTeamConfigLogic)
    const { githubIntegrations } = useValues(integrationsLogic)

    const integrationId = draftBaseBranchIntegrationId ?? githubIntegrations[0].id

    return (
        <div className="flex flex-wrap items-center gap-1">
            {githubIntegrations.length > 1 && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="sm"
                                aria-label="GitHub organization"
                                disabled={teamConfigUpdating}
                            >
                                <span className="min-w-0 truncate">
                                    {githubIntegrations.find((integration) => integration.id === integrationId)
                                        ?.display_name ?? 'GitHub'}
                                </span>
                            </Button>
                        }
                    />
                    <DropdownMenuContent>
                        {githubIntegrations.map((integration) => (
                            <DropdownMenuItem
                                key={integration.id}
                                onClick={() => setDraftBaseBranchIntegrationId(integration.id)}
                            >
                                {integration.display_name}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            <ButtonGroup>
                <GitHubRepositoryCombobox
                    integrationId={integrationId}
                    value={draftBaseBranchRepo}
                    disabled={teamConfigUpdating}
                    onChange={(repo) => setDraftBaseBranchRepo(repo ?? '')}
                    placeholder="Repository"
                />
                {draftBaseBranchRepo ? (
                    <GitHubBranchCombobox
                        integrationId={integrationId}
                        repo={draftBaseBranchRepo}
                        value={draftBaseBranchBranch}
                        allowCustomValues={false}
                        disabled={teamConfigUpdating}
                        onChange={(branch) => setDraftBaseBranchBranch(branch ?? '')}
                    />
                ) : null}
            </ButtonGroup>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={!!addBaseBranchOverrideDisabledReason}
                            loading={teamConfigUpdating}
                            aria-label="Add base branch override"
                            onClick={() => addBaseBranchOverride()}
                        >
                            <IconPlus />
                            Add
                        </Button>
                    }
                />
                <TooltipContent>{addBaseBranchOverrideDisabledReason ?? 'Add base branch override'}</TooltipContent>
            </Tooltip>
        </div>
    )
}

/**
 * Collapsed by default, because targeting anything but the repo's default branch is the exception.
 * Opens on its own when overrides exist, so a configured team isn't left to discover them behind a
 * chevron; the count keeps that state readable even once collapsed again.
 */
function BaseBranchOverrides(): JSX.Element {
    const { baseBranchOverrides } = useValues(signalTeamConfigLogic)
    const { githubIntegrations } = useValues(integrationsLogic)

    // The Collapsible root fills itself with --muted while open or hovered, which reads as an
    // off-color patch against the card. The trigger owns the hover instead.
    return (
        <Collapsible defaultOpen={baseBranchOverrides.length > 0} className="bg-transparent hover:bg-transparent">
            {/* px-2.5/py-1.5 matches the Threshold row above; the Button's own fill is dropped so the
                row reads as a label, not a band, leaving only the hover as the affordance. */}
            <CollapsibleTrigger className="w-full h-auto px-2.5 py-1.5 text-xs text-secondary font-normal bg-transparent hover:bg-[var(--fill-hover)]">
                <span className="flex-1 text-left">Base branch overrides</span>
                {baseBranchOverrides.length > 0 && (
                    <span className="text-tertiary tabular-nums">{baseBranchOverrides.length}</span>
                )}
            </CollapsibleTrigger>
            {/* Padding goes on the panel itself rather than a nested wrapper, which would stack with
                the panel's own inset. Same 10px/6px as the trigger and the Threshold row. */}
            <CollapsibleContent className="flex flex-col gap-1.5 px-2.5 pb-1.5">
                <p className="text-[11px] text-tertiary leading-snug mb-0">
                    Otherwise, PRs use GitHub's default branch.
                </p>
                <BaseBranchOverrideRows />
                {githubIntegrations.length > 0 ? (
                    <BaseBranchOverridePicker />
                ) : (
                    <p className="text-[11px] text-tertiary leading-snug mb-0">
                        Connect GitHub above to add an override.
                    </p>
                )}
            </CollapsibleContent>
        </Collapsible>
    )
}

/**
 * A self-imposed cap on reports per day, deliberately housed with the autonomy throttles rather
 * than the billing usage card: it is "how much should the agents do", not "what does the plan
 * allow", and placing it next to plan usage read as if the two limits were one system. Renders
 * regardless of the auto-start toggle, since the cap pauses report generation, not just PRs.
 * While the billing quota has the pipeline paused, the live count is withheld so remaining daily
 * headroom is not advertised on a day when nothing will arrive. Same collapsed-by-default shape
 * as Base branch overrides: the trigger's count keeps the state readable without opening.
 */
function DailyReportLimit(): JSX.Element {
    const {
        maxReportsPerDay,
        reportsGeneratedToday,
        dailyReportLimitReached,
        draftMaxReportsPerDay,
        saveMaxReportsPerDayDisabledReason,
        teamConfigUpdating,
    } = useValues(signalTeamConfigLogic)
    const { setDraftMaxReportsPerDay, saveDraftMaxReportsPerDay } = useActions(signalTeamConfigLogic)
    const { quotaLimited } = useValues(inboxUsageLogic)

    const summary = quotaLimited
        ? 'Paused by plan limit'
        : maxReportsPerDay != null
          ? `${Math.min(reportsGeneratedToday, maxReportsPerDay)} / ${maxReportsPerDay} today`
          : null

    return (
        <>
            <Collapsible className="bg-transparent hover:bg-transparent">
                <CollapsibleTrigger className="w-full h-auto px-2.5 py-1.5 text-xs text-secondary font-normal bg-transparent hover:bg-[var(--fill-hover)]">
                    <span className="flex-1 text-left">Daily report limit</span>
                    {summary && <span className="text-tertiary tabular-nums">{summary}</span>}
                </CollapsibleTrigger>
                <CollapsibleContent className="flex flex-col gap-1.5 px-2.5 pb-1.5">
                    <p className="text-[11px] text-tertiary leading-snug mb-0">
                        Pause new report generation after this many reports in a day. Leave empty for no limit.
                    </p>
                    <div className="flex items-center gap-1">
                        <LemonInput
                            type="number"
                            min={1}
                            step={1}
                            size="small"
                            placeholder="No limit"
                            value={draftMaxReportsPerDay ?? undefined}
                            onChange={(value) => setDraftMaxReportsPerDay(value ?? null)}
                            onPressEnter={saveDraftMaxReportsPerDay}
                            fullWidth
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={saveDraftMaxReportsPerDay}
                            loading={teamConfigUpdating}
                            disabledReason={saveMaxReportsPerDayDisabledReason ?? undefined}
                            data-attr="signals-daily-report-limit-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </CollapsibleContent>
            </Collapsible>
            {dailyReportLimitReached && !quotaLimited && (
                <p className="text-xs font-medium text-danger mb-0 px-2.5 pb-1.5">
                    Daily report limit reached. New reports resume at midnight in your project's timezone.
                </p>
            )}
        </>
    )
}

/**
 * Team-wide PR-generation control, backed by `autostart_enabled` and `default_autostart_priority`
 * on `signalTeamConfigLogic`. The inline switch is the master opt-out for autonomous inbox PRs;
 * reports keep generating and notifying either way. The threshold is the team default; a teammate's
 * personal threshold takes precedence for reports suggesting them as reviewer.
 *
 * A standalone card rather than a `SetupWidgetCard` because it hosts inline controls (the switch and
 * threshold) that can't live inside that card's single button/link wrapper.
 */
export function SelfDrivingSection(): JSX.Element {
    const { teamConfig, teamConfigLoading, teamConfigUpdating, autostartEnabled, defaultAutostartPriority } =
        useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)
    const { autonomyConfig, autonomyConfigLoading, autostartPriorityUpdating } = useValues(userAutonomyLogic)
    const { setAutostartPriority } = useActions(userAutonomyLogic)
    const myThreshold = autonomyConfig?.autostart_priority ?? MY_THRESHOLD_DEFAULT_VALUE

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-20 w-full rounded" />
    }

    return (
        <div className="flex flex-col rounded border border-primary bg-surface-primary overflow-hidden">
            <div className="flex items-start gap-2 px-2.5 py-2">
                <span className="flex size-7 shrink-0 items-center justify-center rounded bg-surface-secondary text-default [&_svg]:size-4">
                    <IconRocket />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[13px] font-semibold text-default">PR generation</span>
                        <LemonSwitch
                            checked={autostartEnabled}
                            loading={teamConfigUpdating}
                            onChange={(enabled) => patchTeamConfig({ autostart_enabled: enabled })}
                            aria-label="Generate PRs for actionable reports automatically"
                        />
                    </div>
                    <p className="text-xs text-tertiary leading-snug mb-0">Agents open PRs for actionable reports.</p>
                </div>
            </div>

            <div className="border-t border-primary bg-surface-secondary">
                {autostartEnabled ? (
                    <>
                        {/* Label above the control rather than beside it: the rail is narrow enough that a
                            five- or six-segment row alongside a label overflows the card. `fullWidth` keeps the
                            segments even, capped so the same markup doesn't stretch in the wide stacked layout. */}
                        <div className="flex flex-col gap-2 px-2.5 py-1.5">
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-secondary">Project threshold</span>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    fullWidth
                                    className="max-w-xs"
                                    value={defaultAutostartPriority}
                                    options={THRESHOLD_SEGMENTS}
                                    disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                                    onChange={(next) => patchTeamConfig({ default_autostart_priority: next })}
                                />
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-xs text-secondary">My threshold</span>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    fullWidth
                                    className="max-w-xs"
                                    value={myThreshold}
                                    options={MY_THRESHOLD_SEGMENTS}
                                    disabledReason={
                                        autostartPriorityUpdating
                                            ? 'Saving changes'
                                            : autonomyConfigLoading
                                              ? 'Loading settings'
                                              : undefined
                                    }
                                    onChange={(next) =>
                                        setAutostartPriority(
                                            next === MY_THRESHOLD_DEFAULT_VALUE ? null : (next as SignalReportPriority)
                                        )
                                    }
                                />
                                <p className="text-[11px] text-tertiary leading-snug mb-0">
                                    Overrides the project threshold for reports that suggest you as reviewer. It applies
                                    across all your projects.
                                </p>
                            </div>
                        </div>
                        <div className="border-t border-primary">
                            <BaseBranchOverrides />
                        </div>
                    </>
                ) : (
                    <p className="text-xs text-secondary mb-0 px-2.5 py-1.5">
                        Reports still arrive and notify your team.
                    </p>
                )}
                <div className="border-t border-primary">
                    <DailyReportLimit />
                </div>
            </div>
        </div>
    )
}
