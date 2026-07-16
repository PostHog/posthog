import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonSwitch, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ReviewModeEnumApi, type StamphogRepoConfigApi } from '../../generated/api.schemas'
import { stamphogSceneLogic } from './stamphogSceneLogic'

export const scene: SceneExport = {
    component: StamphogScene,
    logic: stamphogSceneLogic,
}

function ConnectRepositoryButton(): JSX.Element {
    const { installUrl, installInfoLoading } = useValues(stamphogSceneLogic)
    return (
        <LemonButton
            type="primary"
            icon={<IconGithub />}
            to={installUrl || undefined}
            targetBlank
            disableClientSideRouting
            disabledReason={
                installInfoLoading
                    ? 'Loading install details'
                    : installUrl
                      ? undefined
                      : 'GitHub App not configured yet'
            }
        >
            Connect a repository
        </LemonButton>
    )
}

function SyncedBanner(): JSX.Element | null {
    const { syncedRepos, skippedRepos } = useValues(stamphogSceneLogic)

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
    const { setReviewMode, setTriggerLabel } = useActions(stamphogSceneLogic)

    const saveTriggerLabel = (value: string): void => {
        const trimmed = value.trim()
        // Save only real changes — blur after no edit (or after enter already saved) must not re-PATCH,
        // and a blank label is rejected by the API anyway.
        if (trimmed && trimmed !== repo.trigger_label) {
            setTriggerLabel(repo.id, trimmed)
        }
    }

    return (
        <div className="flex items-center gap-2">
            <LemonSelect
                size="small"
                value={repo.review_mode ?? ReviewModeEnumApi.All}
                disabledReason={updating ? 'Updating' : undefined}
                onChange={(mode) => setReviewMode(repo.id, mode)}
                options={[
                    { value: ReviewModeEnumApi.All, label: 'All PRs' },
                    { value: ReviewModeEnumApi.Label, label: 'Label-triggered' },
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
                    disabled={updating}
                    onBlur={(e) => saveTriggerLabel(e.currentTarget.value)}
                    onPressEnter={(e) => saveTriggerLabel(e.currentTarget.value)}
                />
            )}
        </div>
    )
}

function RepoConfigsTable(): JSX.Element {
    const { filteredRepoConfigs, repoConfigs, repoConfigsLoading, updatingRepoIds, repoSearch } =
        useValues(stamphogSceneLogic)
    const { setRepoEnabled, setDigestEnabled, setRepoSearch } = useActions(stamphogSceneLogic)

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
                    disabledReason={updatingRepoIds.includes(repo.id) ? 'Updating' : undefined}
                    onChange={(checked) => setRepoEnabled(repo.id, checked)}
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
                    disabledReason={updatingRepoIds.includes(repo.id) ? 'Updating' : undefined}
                    onChange={(checked) => setDigestEnabled(repo.id, checked)}
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
                <LemonInput
                    type="search"
                    placeholder="Search repositories"
                    value={repoSearch}
                    onChange={setRepoSearch}
                    className="max-w-100"
                />
            )}
            <LemonTable
                columns={columns}
                dataSource={filteredRepoConfigs}
                loading={repoConfigsLoading}
                rowKey="id"
                pagination={{ pageSize: 20 }}
                emptyState="No repositories yet. Install the Stamphog GitHub App to get started."
            />
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
            <SyncedBanner />
            <div>
                <h3>Repositories</h3>
                <RepoConfigsTable />
            </div>
        </SceneContent>
    )
}

export default StamphogScene
