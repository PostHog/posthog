import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
    Link,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { GitHubBranchCombobox } from 'lib/integrations/GitHubBranchCombobox'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { JiraProjectPicker } from 'lib/integrations/JiraIntegrationHelpers'
import { LinearTeamPicker } from 'lib/integrations/LinearIntegrationHelpers'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { PRIORITY_THRESHOLD_OPTIONS, SignalReportPriority } from '../../types'
import { AutonomySettingGroup } from './AutonomySettingGroup'
import { AutonomySettingRow } from './AutonomySettingRow'

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

const PR_STATE_SEGMENTS = [
    { value: 'draft', label: 'Draft' },
    { value: 'ready', label: 'Ready for review' },
]
const MY_PR_STATE_DEFAULT_VALUE = '__default__'
const MY_PR_STATE_SEGMENTS = [{ value: MY_PR_STATE_DEFAULT_VALUE, label: 'Default' }, ...PR_STATE_SEGMENTS]

function BaseBranchOverrideList(): JSX.Element | null {
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
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {baseBranchOverrides.map(({ repo, branch }) => {
                const integration = integrationsByOwner.get(repo.split('/')[0])
                return (
                    <li key={repo} className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 flex-1 basis-40 truncate text-sm text-default" title={repo}>
                            {repo}
                        </span>
                        <div className="flex items-center gap-1">
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
                                <span className="text-xs text-secondary">{branch}</span>
                            )}
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconX />}
                                loading={teamConfigUpdating}
                                aria-label={`Remove base branch override for ${repo}`}
                                data-attr="signals-base-branch-override-remove"
                                onClick={() => removeBaseBranchOverride(repo)}
                            />
                        </div>
                    </li>
                )
            })}
        </ul>
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
                <LemonSelect
                    size="small"
                    value={integrationId}
                    options={githubIntegrations.map((integration) => ({
                        value: integration.id,
                        label: integration.display_name,
                    }))}
                    disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                    onChange={(next) => next != null && setDraftBaseBranchIntegrationId(next)}
                    aria-label="GitHub organization"
                />
            )}
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
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                disabledReason={addBaseBranchOverrideDisabledReason ?? undefined}
                loading={teamConfigUpdating}
                data-attr="signals-base-branch-override-add"
                onClick={() => addBaseBranchOverride()}
            >
                Add override
            </LemonButton>
        </div>
    )
}

/**
 * Where agents branch from, per repository. Only shown while PR generation is on: the list and the
 * picker stay in view so a configured team can read its overrides without opening anything.
 */
function BaseBranchesRow(): JSX.Element {
    const { githubIntegrations } = useValues(integrationsLogic)

    return (
        <AutonomySettingRow
            title="Base branches"
            description={
                githubIntegrations.length > 0 ? (
                    'PRs target the default branch of each repository. Add an override for a repository that needs a different branch.'
                ) : (
                    <>
                        PRs target the default branch of each repository.{' '}
                        <Link to={urls.settings('project-integrations')}>Connect GitHub</Link> to add an override.
                    </>
                )
            }
        >
            {githubIntegrations.length > 0 && (
                <div className="flex flex-col gap-2 py-3">
                    <BaseBranchOverrideList />
                    <BaseBranchOverridePicker />
                </div>
            )}
        </AutonomySettingRow>
    )
}

/** Providers that can hold a tracker issue, with the label the picker shows for each. */
const ISSUE_TRACKER_LABELS: Partial<Record<IntegrationType['kind'], string>> = {
    github: 'GitHub issues',
    linear: 'Linear',
    jira: 'Jira',
    gitlab: 'GitLab issues',
}

/** LemonSelect has no null option value, so "off" needs a sentinel that no integration id can take. */
const ISSUE_TRACKER_OFF = -1

/**
 * Where inside the chosen tracker the issues land. The shape follows the provider, so this renders
 * one picker per provider. GitLab needs no pick at all: its integration is already bound to one
 * project.
 */
function IssueTrackerTarget({
    integration,
    target,
    disabled,
    onSave,
}: {
    integration: IntegrationType
    target: Record<string, string>
    disabled: boolean
    onSave: (config: Record<string, string>) => void
}): JSX.Element | null {
    if (integration.kind === 'github') {
        return (
            <GitHubRepositoryCombobox
                integrationId={integration.id}
                // Stored bare so the issue link can re-prefix the account that owns it, while the
                // picker works in the `owner/repo` form it shows.
                value={target.repository ? `${integration.display_name}/${target.repository}` : ''}
                disabled={disabled}
                placeholder="Repository"
                onChange={(repo) => repo && onSave({ ...target, repository: repo.split('/')[1] })}
            />
        )
    }
    if (integration.kind === 'linear') {
        return (
            <LinearTeamPicker
                integration={integration}
                value={target.team_id}
                disabled={disabled}
                onChange={(teamId) => teamId && onSave({ team_id: teamId })}
            />
        )
    }
    if (integration.kind === 'jira') {
        return (
            <JiraProjectPicker
                integrationId={integration.id}
                value={target.project_key ?? ''}
                disabled={disabled}
                onChange={(projectKey) => projectKey && onSave({ project_key: projectKey })}
            />
        )
    }
    return <p className="m-0 text-xs text-secondary">Issues go to {integration.display_name}.</p>
}

/**
 * Per-project switch for the change-management control some teams work under: a pull request can
 * only merge when a tracked work item points at it. Off unless a tracker is picked, so one field is
 * both the switch and the target and the two can never disagree.
 */
function IssueTrackerRow(): JSX.Element {
    const { issueTrackerConfig, issueTrackerIntegrationId, selectedIssueTrackerIntegrationId, teamConfigUpdating } =
        useValues(signalTeamConfigLogic)
    const { patchTeamConfig, setDraftIssueTrackerIntegrationId } = useActions(signalTeamConfigLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    const trackers = (integrations ?? []).filter((integration) => integration.kind in ISSUE_TRACKER_LABELS)
    const selected = trackers.find((integration) => integration.id === selectedIssueTrackerIntegrationId) ?? null
    // A freshly picked provider has no target yet, so the stored one belongs to the old provider.
    const target = selectedIssueTrackerIntegrationId === issueTrackerIntegrationId ? issueTrackerConfig : {}

    const saveTarget = (config: Record<string, string>): void => {
        if (selected) {
            patchTeamConfig({
                issue_tracking_integration: selected.id,
                issue_tracking_config: { ...target, ...config },
            })
        }
    }

    const chooseTracker = (next: number): void => {
        if (next === ISSUE_TRACKER_OFF) {
            setDraftIssueTrackerIntegrationId(null)
            patchTeamConfig({ issue_tracking_integration: null, issue_tracking_config: {} })
            return
        }

        setDraftIssueTrackerIntegrationId(next)
        if (trackers.find((integration) => integration.id === next)?.kind === 'gitlab') {
            patchTeamConfig({ issue_tracking_integration: next, issue_tracking_config: {} })
        }
    }

    let control: JSX.Element
    if (integrations === null) {
        control = integrationsLoading ? (
            <LemonSkeleton className="h-8 w-40" />
        ) : (
            <LemonButton size="small" type="secondary" onClick={() => loadIntegrations()}>
                Retry
            </LemonButton>
        )
    } else if (trackers.length === 0) {
        control = (
            <LemonButton
                size="small"
                type="secondary"
                to={urls.settings('project-integrations')}
                data-attr="signals-issue-tracker-connect"
            >
                Connect a tracker
            </LemonButton>
        )
    } else {
        control = (
            <LemonSelect
                size="small"
                value={selectedIssueTrackerIntegrationId ?? ISSUE_TRACKER_OFF}
                options={[
                    { value: ISSUE_TRACKER_OFF, label: 'Off' },
                    ...trackers.map((integration) => ({
                        value: integration.id,
                        label: `${ISSUE_TRACKER_LABELS[integration.kind]} · ${integration.display_name}`,
                    })),
                ]}
                disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                onChange={chooseTracker}
                aria-label="Issue tracker"
            />
        )
    }

    return (
        <AutonomySettingRow
            title="Issue tracker"
            description={
                <>
                    Open an issue for every PR agents make, and link the two. Use this when a PR can only merge with a
                    tracked work item behind it.
                    {integrations !== null && trackers.length === 0 && ' Works with GitHub, GitLab, Linear, and Jira.'}
                    {integrations === null && !integrationsLoading && ' Could not load integrations.'}
                </>
            }
            control={control}
        >
            {selected && (
                <div className="flex flex-col gap-2 py-3">
                    <IssueTrackerTarget
                        integration={selected}
                        target={target}
                        disabled={teamConfigUpdating}
                        onSave={saveTarget}
                    />
                    <p className="m-0 text-xs leading-snug text-secondary">
                        If the tracker fails, the PR still opens and the report shows that the issue is missing.
                    </p>
                </div>
            )}
        </AutonomySettingRow>
    )
}

/**
 * A self-imposed cap on reports per day, deliberately housed with the autonomy throttles rather
 * than the billing usage card: it is "how much should the agents do", not "what does the plan
 * allow", and placing it next to plan usage read as if the two limits were one system. Renders
 * regardless of the auto-start toggle, since the cap pauses report generation, not just PRs.
 * The billing quota deliberately does not overwrite this row: it caps pull requests, not reports,
 * so stamping its pause here reported the wrong limit as the reason nothing arrived.
 */
function DailyReportLimitRow(): JSX.Element {
    const {
        maxReportsPerDay,
        reportsGeneratedToday,
        dailyReportLimitReached,
        draftMaxReportsPerDay,
        saveMaxReportsPerDayDisabledReason,
        teamConfigUpdating,
    } = useValues(signalTeamConfigLogic)
    const { setDraftMaxReportsPerDay, saveDraftMaxReportsPerDay } = useActions(signalTeamConfigLogic)

    const usage =
        maxReportsPerDay != null
            ? `${Math.min(reportsGeneratedToday, maxReportsPerDay)} of ${maxReportsPerDay} reports today.`
            : null

    return (
        <AutonomySettingRow
            title="Daily report limit"
            description={
                <>
                    Pause new reports after this many in a day. Leave empty for no limit.
                    {usage && (
                        <>
                            {' '}
                            <span className="text-default tabular-nums" translate="no">
                                {usage}
                            </span>
                        </>
                    )}
                    {dailyReportLimitReached && (
                        <span className="block font-medium text-danger">
                            Daily report limit reached. New reports resume at midnight in your project's timezone.
                        </span>
                    )}
                </>
            }
            control={
                <>
                    <LemonInput
                        type="number"
                        min={1}
                        step={1}
                        size="small"
                        className="w-28"
                        placeholder="No limit"
                        value={draftMaxReportsPerDay ?? undefined}
                        onChange={(value) => setDraftMaxReportsPerDay(value ?? null)}
                        onPressEnter={saveDraftMaxReportsPerDay}
                        aria-label="Daily report limit"
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
                </>
            }
        />
    )
}

/**
 * Team-wide opt-in to commenting back on a GitHub issue that raised a report. Off by default,
 * because the comment is public on the issue thread. It carries a link to the report and nothing
 * else, so what the report says stays behind the project's own access check.
 */
function GitHubIssueWritebackRow(): JSX.Element {
    const { githubIssueWritebackEnabled, teamConfigUpdating } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    return (
        <AutonomySettingRow
            title="Comment back on GitHub issues"
            description="When a GitHub issue creates a report, comment on that issue with a link to the report. Everybody watching the issue can see the comment."
            control={
                <LemonSwitch
                    checked={githubIssueWritebackEnabled}
                    loading={teamConfigUpdating}
                    onChange={(enabled) => patchTeamConfig({ github_issue_writeback_enabled: enabled })}
                    aria-label="Comment back on GitHub issues that create reports"
                    data-attr="signals-github-issue-writeback"
                />
            }
        />
    )
}

/**
 * Per-user opt-in to being added as a GitHub assignee on the implementation PR for reports that
 * suggest this user as reviewer. Off by default, because being assigned is visible to everybody on
 * the pull request. Renders regardless of the auto-start toggle: a PR opened by hand from the inbox
 * assigns reviewers too.
 */
function GitHubAssignmentRow(): JSX.Element {
    const { autonomyConfig, autonomyConfigLoading, githubAssignUpdating } = useValues(userAutonomyLogic)
    const { setGithubAssignOnPullRequest } = useActions(userAutonomyLogic)

    return (
        <AutonomySettingRow
            title="Assign me on GitHub"
            description="Add you as an assignee on the PRs agents open for your reports."
            control={
                <LemonSwitch
                    checked={autonomyConfig?.github_assign_on_pull_request ?? false}
                    loading={githubAssignUpdating}
                    disabledReason={autonomyConfigLoading && autonomyConfig === null ? 'Loading settings' : undefined}
                    onChange={setGithubAssignOnPullRequest}
                    aria-label="Assign me on GitHub pull requests"
                    data-attr="signals-github-assign-on-pull-request"
                />
            }
        />
    )
}

/**
 * Whether self-driving PRs skip the draft state. Draft stays the default because a ready PR runs
 * the full CI matrix on every push. Renders regardless of the auto-start toggle: a PR opened by
 * hand from the inbox goes through the same transition.
 */
function ProjectPullRequestStateRow(): JSX.Element {
    const { defaultOpenPullRequestReady, teamConfigUpdating } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    return (
        <AutonomySettingRow
            title="Open PRs as"
            description="Draft lets your team inspect the change first. Ready for review can run more checks and request reviews, as your repository settings allow."
            control={
                <LemonSegmentedButton
                    size="small"
                    value={defaultOpenPullRequestReady ? 'ready' : 'draft'}
                    options={PR_STATE_SEGMENTS}
                    disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                    onChange={(next) => patchTeamConfig({ default_open_pull_request_ready: next === 'ready' })}
                />
            }
        />
    )
}

/** The personal counterpart: one reviewer's workflow differs from their teammate's, so it wins. */
function MyPullRequestStateRow(): JSX.Element {
    const { autonomyConfig, autonomyConfigLoading, openPullRequestReadyUpdating } = useValues(userAutonomyLogic)
    const { setOpenPullRequestReady } = useActions(userAutonomyLogic)

    const mine = autonomyConfig?.github_open_pull_request_ready
    const myState = mine == null ? MY_PR_STATE_DEFAULT_VALUE : mine ? 'ready' : 'draft'

    return (
        <AutonomySettingRow
            title="Open PRs as"
            description="Default follows the project setting. A PR stays in draft if someone moves it back to draft."
            control={
                <LemonSegmentedButton
                    size="small"
                    value={myState}
                    options={MY_PR_STATE_SEGMENTS}
                    disabledReason={
                        openPullRequestReadyUpdating
                            ? 'Saving changes'
                            : autonomyConfigLoading && autonomyConfig === null
                              ? 'Loading settings'
                              : undefined
                    }
                    onChange={(next) =>
                        setOpenPullRequestReady(next === MY_PR_STATE_DEFAULT_VALUE ? null : next === 'ready')
                    }
                />
            }
        />
    )
}

/** The team default; a teammate's personal threshold takes precedence for reports suggesting them. */
function ProjectThresholdRow(): JSX.Element {
    const { defaultAutostartPriority, teamConfigUpdating } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    return (
        <AutonomySettingRow
            title="Priority threshold"
            description="Agents open PRs for reports at this priority or higher."
            control={
                <LemonSegmentedButton
                    size="small"
                    value={defaultAutostartPriority}
                    options={THRESHOLD_SEGMENTS}
                    disabledReason={teamConfigUpdating ? 'Saving changes' : undefined}
                    onChange={(next) => patchTeamConfig({ default_autostart_priority: next })}
                />
            }
        />
    )
}

function MyThresholdRow(): JSX.Element {
    const { autonomyConfig, autonomyConfigLoading, autostartPriorityUpdating } = useValues(userAutonomyLogic)
    const { setAutostartPriority } = useActions(userAutonomyLogic)
    const myThreshold = autonomyConfig?.autostart_priority ?? MY_THRESHOLD_DEFAULT_VALUE

    return (
        <AutonomySettingRow
            title="Priority threshold"
            description="Default follows the project threshold."
            control={
                <LemonSegmentedButton
                    size="small"
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
            }
        />
    )
}

/**
 * Team-wide PR-generation control, backed by `autostart_enabled` and `default_autostart_priority`
 * on `signalTeamConfigLogic`. The switch is the master opt-out for autonomous inbox PRs; reports
 * keep generating and notifying either way. The threshold and base branches only matter while it
 * is on, so they nest under it.
 */
function PullRequestGenerationRow(): JSX.Element {
    const { teamConfigUpdating, autostartEnabled } = useValues(signalTeamConfigLogic)
    const { patchTeamConfig } = useActions(signalTeamConfigLogic)

    return (
        <AutonomySettingRow
            title="PR generation"
            description={
                autostartEnabled
                    ? 'Agents open PRs for actionable reports.'
                    : 'Reports still arrive and notify your team. Turn this on to let agents open PRs for actionable reports.'
            }
            control={
                <LemonSwitch
                    checked={autostartEnabled}
                    loading={teamConfigUpdating}
                    onChange={(enabled) => patchTeamConfig({ autostart_enabled: enabled })}
                    aria-label="Generate PRs for actionable reports automatically"
                    data-attr="signals-autostart-enabled"
                />
            }
        >
            {autostartEnabled && (
                <>
                    <ProjectThresholdRow />
                    <BaseBranchesRow />
                </>
            )}
        </AutonomySettingRow>
    )
}

/**
 * The Autonomy settings: what agents do on their own for this project, the current user's personal
 * overrides, and the daily report cap. Rows group by scope so a setting does not have to say who it
 * applies to, and every row shares one shape (`AutonomySettingRow`).
 */
export function SelfDrivingSection(): JSX.Element {
    // The Settings tab wraps this in its own card; the legacy setup rail does not.
    const redesign = useFeatureFlag('INBOX_REDESIGN')
    const { teamConfig, teamConfigLoading, autostartEnabled } = useValues(signalTeamConfigLogic)

    if (teamConfigLoading && teamConfig === null) {
        return <LemonSkeleton className="h-20 w-full rounded" />
    }

    return (
        <div
            className={
                redesign
                    ? 'flex flex-col divide-y divide-primary'
                    : 'flex flex-col divide-y divide-primary rounded border border-primary bg-surface-primary px-3 py-3'
            }
        >
            <AutonomySettingGroup title="Pull requests" description="Applies to everyone in this project.">
                <PullRequestGenerationRow />
                <ProjectPullRequestStateRow />
                <GitHubIssueWritebackRow />
                <IssueTrackerRow />
            </AutonomySettingGroup>
            <AutonomySettingGroup
                title="Your overrides"
                description="For reports that suggest you as reviewer, in every project you belong to. These override the project settings."
            >
                {autostartEnabled && <MyThresholdRow />}
                <MyPullRequestStateRow />
                <GitHubAssignmentRow />
            </AutonomySettingGroup>
            <AutonomySettingGroup title="Reports">
                <DailyReportLimitRow />
            </AutonomySettingGroup>
        </div>
    )
}
