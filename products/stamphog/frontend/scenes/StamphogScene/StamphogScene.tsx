import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { getAccessControlDisabledReason, toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { StamphogTabs } from '../../components/StamphogTabs'
import { ReviewModeEnumApi, type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { REVIEW_MODE_LABELS } from '../../reviewModeLabels'
import { type RepoStatusFilter, stamphogSceneLogic } from './stamphogSceneLogic'

// Whether a repository is reviewed at all is a manager decision. The digest only changes who hears
// about the work, and connecting a repository starts no review on its own, so both stay at editor.
//
// The level comes from the API rather than the app context, because the app context answers for the
// environment in the URL while these rows belong to its parent project. Undefined when no repository
// has loaded yet, which sends the check back to the app context.
const managerDisabledReason = (level: AccessControlLevel | undefined): string | null =>
    getAccessControlDisabledReason(AccessControlResourceType.Stamphog, AccessControlLevel.Manager, level)
const editorDisabledReason = (level: AccessControlLevel | undefined): string | null =>
    getAccessControlDisabledReason(AccessControlResourceType.Stamphog, AccessControlLevel.Editor, level)

export const scene: SceneExport = {
    component: StamphogScene,
    logic: stamphogSceneLogic,
}

function ConnectRepositoryButton(): JSX.Element {
    const { installInfo, installUrl, installInfoLoading, stamphogAccessLevel } = useValues(stamphogSceneLogic)
    // The callback finishes through the authorize URL, so an install link alone cannot connect anything.
    const canConnect = !!installUrl && !!installInfo?.authorize_url
    return (
        <LemonButton
            type="primary"
            icon={<IconGithub />}
            to={canConnect ? installUrl : undefined}
            disableClientSideRouting
            data-attr="stamphog-connect-repository"
            disabledReason={
                editorDisabledReason(stamphogAccessLevel) ??
                (installInfoLoading
                    ? 'Loading install details'
                    : canConnect
                      ? undefined
                      : 'GitHub App not configured yet')
            }
        >
            Connect a repository
        </LemonButton>
    )
}

function SyncedBanner(): JSX.Element | null {
    const { syncedRepos, skippedRepos, appNotInstalled, installUrl, discoveredInstallations } =
        useValues(stamphogSceneLogic)
    const { connectInstallation } = useActions(stamphogSceneLogic)

    // Discovery found several installations and bound nothing: the user picks which one this team
    // connects. The pick rides sessionStorage through one more (silent) authorize hop, and the
    // backend's explicit-id path verifies it.
    if (discoveredInstallations.length > 0) {
        return (
            <LemonBanner type="info">
                <p className="font-medium">Stamphog is installed on several GitHub accounts</p>
                <p>Pick the one to connect to this project:</p>
                <div className="flex gap-2 flex-wrap">
                    {discoveredInstallations.map((installation) => (
                        <LemonButton
                            key={installation.id}
                            type="secondary"
                            icon={<IconGithub />}
                            onClick={() => connectInstallation(installation.id)}
                        >
                            {installation.account_login}
                        </LemonButton>
                    ))}
                </div>
            </LemonBanner>
        )
    }

    // Discovery found no installation the user can reach: they authorized the App but never installed it
    // on the org. Point them at the GitHub install page (install_url still carries a fresh state token).
    if (appNotInstalled) {
        return (
            <LemonBanner type="warning">
                <p className="font-medium">Stamphog isn't installed on GitHub yet</p>
                <p>
                    Install the Stamphog GitHub App on your organization to connect its repositories.
                    {installUrl && (
                        <>
                            {' '}
                            <Link to={installUrl} target="_blank" disableClientSideRouting>
                                Install on GitHub
                            </Link>
                        </>
                    )}
                </p>
            </LemonBanner>
        )
    }

    if (syncedRepos.length === 0 && skippedRepos.length === 0) {
        return null
    }

    // A sync can connect nothing (every repo already owned by another team) — that still needs
    // an explanation, not a silent no-op.
    return (
        <LemonBanner type={syncedRepos.length > 0 ? 'success' : 'warning'}>
            {syncedRepos.length > 0 ? (
                <>
                    <p className="font-medium">Connected {syncedRepos.length} repositories</p>
                    <p>Stamphog isn't reviewing them yet. Turn on the ones you want reviewed in the table below.</p>
                </>
            ) : (
                <p className="font-medium">No repositories connected</p>
            )}
            {skippedRepos.length > 0 && (
                <p className={syncedRepos.length > 0 ? 'text-warning mt-2' : 'mt-2'}>
                    Skipped {skippedRepos.join(', ')} because another team already owns them under this installation.
                </p>
            )}
        </LemonBanner>
    )
}

function ReviewModeCell({ repo, updating }: { repo: StamphogRepoConfigApi; updating: boolean }): JSX.Element {
    const { updateRepoConfig } = useActions(stamphogSceneLogic)
    const disabledReason =
        managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ?? (updating ? 'Updating' : undefined)

    const saveTriggerLabel = (value: string): void => {
        const trimmed = value.trim()
        // Save only real changes — blur after no edit (or after enter already saved) must not re-PATCH,
        // and a blank label is rejected by the API anyway.
        if (trimmed && trimmed !== repo.trigger_label) {
            updateRepoConfig(repo.id, { trigger_label: trimmed })
        }
    }

    return (
        <div className="flex items-center gap-2">
            <LemonSelect
                size="small"
                value={repo.review_mode ?? ReviewModeEnumApi.All}
                disabledReason={disabledReason}
                onChange={(mode) => updateRepoConfig(repo.id, { review_mode: mode })}
                options={[
                    { value: ReviewModeEnumApi.All, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.All] },
                    { value: ReviewModeEnumApi.Label, label: REVIEW_MODE_LABELS[ReviewModeEnumApi.Label] },
                ]}
            />
            {repo.review_mode === ReviewModeEnumApi.Label && (
                <LemonInput
                    // Uncontrolled on purpose: the label saves on blur/enter, not per keystroke.
                    // Keying by the saved value resets the draft after a reload.
                    key={`${repo.id}-${repo.trigger_label}`}
                    size="small"
                    className="w-40"
                    defaultValue={repo.trigger_label}
                    placeholder="Trigger label"
                    disabledReason={disabledReason}
                    onBlur={(e) => saveTriggerLabel(e.currentTarget.value)}
                    onPressEnter={(e) => saveTriggerLabel(e.currentTarget.value)}
                />
            )}
        </div>
    )
}

function RepoConfigsTable(): JSX.Element {
    const {
        visibleRepoConfigs,
        filteredRepoConfigs,
        repoConfigs,
        repoConfigsLoading,
        updatingRepoIds,
        repoSearch,
        repoStatusFilter,
        repoStatusCounts,
    } = useValues(stamphogSceneLogic)
    const { updateRepoConfig, setRepoSearch, setRepoStatusFilter, showAllRepos } = useActions(stamphogSceneLogic)

    const columns: LemonTableColumns<StamphogRepoConfigApi> = [
        {
            title: 'Repository',
            dataIndex: 'repository',
            render: (repository) => <span className="font-medium">{repository as string}</span>,
        },
        {
            title: 'Enabled',
            key: 'enabled',
            render: (_, repo) => (
                <LemonSwitch
                    checked={!!repo.enabled}
                    disabledReason={
                        managerDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
                        (updatingRepoIds.includes(repo.id) ? 'Updating' : undefined)
                    }
                    onChange={(checked) => updateRepoConfig(repo.id, { enabled: checked })}
                />
            ),
        },
        {
            title: 'Review mode',
            key: 'review_mode',
            render: (_, repo) => <ReviewModeCell repo={repo} updating={updatingRepoIds.includes(repo.id)} />,
        },
        {
            title: 'Digest enabled',
            key: 'digest_enabled',
            render: (_, repo) => (
                <LemonSwitch
                    checked={!!repo.digest_enabled}
                    disabledReason={
                        editorDisabledReason(toAccessControlLevel(repo.user_access_level)) ??
                        (updatingRepoIds.includes(repo.id) ? 'Updating' : undefined)
                    }
                    onChange={(checked) => updateRepoConfig(repo.id, { digest_enabled: checked })}
                />
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (created_at) => <TZLabel time={created_at as string} />,
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            {repoConfigs.length > 10 && (
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search repositories"
                        value={repoSearch}
                        onChange={setRepoSearch}
                        className="max-w-100"
                        data-attr="stamphog-repo-search"
                    />
                    <LemonSegmentedButton<RepoStatusFilter>
                        size="small"
                        value={repoStatusFilter}
                        onChange={setRepoStatusFilter}
                        options={[
                            {
                                value: 'all',
                                label: `All (${repoStatusCounts.all})`,
                                'data-attr': 'stamphog-repo-status-filter-all',
                            },
                            {
                                value: 'on',
                                label: `On (${repoStatusCounts.on})`,
                                tooltip: 'Reviews or the digest are turned on',
                                'data-attr': 'stamphog-repo-status-filter-on',
                            },
                            {
                                value: 'off',
                                label: `Off (${repoStatusCounts.off})`,
                                tooltip: 'Connected, with reviews and the digest turned off',
                                'data-attr': 'stamphog-repo-status-filter-off',
                            },
                        ]}
                    />
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={visibleRepoConfigs}
                loading={repoConfigsLoading}
                rowKey="id"
                emptyState={
                    repoConfigs.length === 0
                        ? 'No repositories yet. Install the Stamphog GitHub App to get started.'
                        : 'No repositories match. Clear the search or pick All to see every repository.'
                }
            />
            {filteredRepoConfigs.length > visibleRepoConfigs.length && (
                <div className="flex items-center gap-2 flex-wrap text-secondary">
                    <span>{`Showing ${visibleRepoConfigs.length} of ${filteredRepoConfigs.length}. Search to find a repository, or show the full list.`}</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={showAllRepos}
                        data-attr="stamphog-repo-show-all"
                    >
                        {`Show all ${filteredRepoConfigs.length}`}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function StamphogScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Stamphog"
                description="Automated pull request reviews and merged-PR digests, per repository."
                resourceType={{ type: 'stamphog' }}
                actions={<ConnectRepositoryButton />}
            />
            <StamphogTabs activeKey="repositories" />
            <SyncedBanner />
            <RepoConfigsTable />
        </SceneContent>
    )
}

export default StamphogScene
