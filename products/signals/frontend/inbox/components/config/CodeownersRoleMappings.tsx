import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import type { RoleExternalReferenceApi } from 'products/integrations/frontend/generated/api.schemas'

import { CodeownersRoleMappingRow, codeownersRoleMappingsLogic } from '../../logics/codeownersRoleMappingsLogic'

const MAPPINGS_PAGE_SIZE = 10

function formatDriftDelta(ref: RoleExternalReferenceApi): string | null {
    const { to_add_count, to_remove_count, has_drift } = ref.drift
    if (!has_drift) {
        return null
    }
    const parts: string[] = []
    if (to_add_count > 0) {
        parts.push(`+${to_add_count}`)
    }
    if (to_remove_count > 0) {
        parts.push(`-${to_remove_count}`)
    }
    return parts.length > 0 ? parts.join(', ') : null
}

function RowSyncStatus({
    row,
    saving,
    canManageMappings,
}: {
    row: CodeownersRoleMappingRow
    saving: boolean
    canManageMappings: boolean
}): JSX.Element | null {
    const { applyReferenceSync } = useActions(codeownersRoleMappingsLogic)
    const ref = row.explicitReference
    const actionDisabledReason = !canManageMappings
        ? 'Only organization admins can change role sync'
        : saving
          ? 'Updating role sync'
          : undefined

    if (!ref) {
        if (!row.suggestedRoleName) {
            return null
        }
        return (
            <Tooltip title="Matched automatically from the PostHog role name. Sync GitHub teams or select a role to pin an explicit mapping.">
                <LemonTag size="small" type="muted">
                    <span>Auto-matched:&nbsp;</span>
                    <span translate="no">{row.suggestedRoleName}</span>
                </LemonTag>
            </Tooltip>
        )
    }

    if (ref.orphaned_at !== null) {
        return (
            <Tooltip title="This team was deleted on GitHub. Its PostHog role and members were preserved.">
                <LemonTag size="small" type="warning">
                    Orphaned
                </LemonTag>
            </Tooltip>
        )
    }

    if (ref.sync_mode === 'auto') {
        const count = ref.drift.matched_posthog_member_count
        return (
            <Tooltip
                title={`Automatically synced with GitHub (${count} PostHog ${count === 1 ? 'member' : 'members'}).`}
            >
                <LemonTag size="small" type="success">
                    Synced
                </LemonTag>
            </Tooltip>
        )
    }

    const delta = formatDriftDelta(ref)
    if (ref.sync_mode === 'proposed' || delta !== null) {
        const label = ref.sync_mode === 'proposed' ? 'Proposed' : 'Drift'
        return (
            <div className="flex flex-wrap items-center gap-1">
                <Tooltip title="Pre-existing PostHog role. Choose Sync once to update members now, or Keep in sync to follow future GitHub team changes.">
                    <LemonTag size="small" type="highlight">
                        <span>{label}</span>
                        {delta && <span translate="no">&nbsp;({delta})</span>}
                    </LemonTag>
                </Tooltip>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={actionDisabledReason}
                    onClick={() => applyReferenceSync(row, 'once')}
                    data-attr="signals-codeowners-role-sync-once"
                >
                    Sync once
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabledReason={actionDisabledReason}
                    onClick={() => applyReferenceSync(row, 'auto')}
                    data-attr="signals-codeowners-role-keep-in-sync"
                >
                    Keep in sync
                </LemonButton>
            </div>
        )
    }

    if (ref.last_synced_at !== null) {
        return (
            <LemonButton
                size="xsmall"
                type="tertiary"
                disabledReason={actionDisabledReason}
                onClick={() => applyReferenceSync(row, 'auto')}
                data-attr="signals-codeowners-role-keep-in-sync"
            >
                Keep in sync
            </LemonButton>
        )
    }

    return null
}

function MappingRow({ row }: { row: CodeownersRoleMappingRow }): JSX.Element {
    const { roles, canManageMappings, savingTeamKeys } = useValues(codeownersRoleMappingsLogic)
    const { setTeamRole } = useActions(codeownersRoleMappingsLogic)

    const saving = Boolean(savingTeamKeys[row.key])
    const roleOptions = (roles ?? []).map((role) => ({
        value: role.id,
        label: role.name,
    }))
    const editDisabledReason = !canManageMappings
        ? 'Only organization admins can change role mappings'
        : saving
          ? 'Saving mapping'
          : roleOptions.length === 0
            ? 'Create a PostHog role in organization settings first'
            : undefined

    const repoTooltip =
        row.explicitReference?.orphaned_at != null
            ? 'Deleted on GitHub (PostHog role preserved)'
            : row.repositories.length > 0
              ? `Found in CODEOWNERS: ${row.repositories.join(', ')}`
              : row.explicitReference?.last_synced_at != null
                ? `Synced from GitHub (${row.explicitReference.provider_role_name})`
                : 'Added manually'

    return (
        <div className="flex flex-wrap items-center gap-2 py-0.5">
            <Tooltip title={repoTooltip}>
                <span className="min-w-36 flex-1 truncate font-mono text-xs text-default" translate="no">
                    {row.handle}
                </span>
            </Tooltip>
            <RowSyncStatus row={row} saving={saving} canManageMappings={canManageMappings} />
            <LemonSelect
                size="small"
                className="w-48"
                value={row.selectedRoleId}
                options={roleOptions}
                placeholder={row.suggestedRoleName ? 'Override role' : 'Select PostHog role'}
                disabledReason={editDisabledReason}
                loading={saving}
                onChange={(roleId) => setTeamRole(row, roleId)}
                data-attr="signals-codeowners-role-mapping-select"
            />
            <div className="flex w-6 shrink-0 justify-end">
                {row.explicitReference && (
                    <Tooltip title="Unlink GitHub team mapping (keeps PostHog role)">
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            aria-label={`Remove mapping for ${row.handle}`}
                            disabledReason={
                                !canManageMappings
                                    ? 'Only organization admins can change role mappings'
                                    : saving
                                      ? 'Saving mapping'
                                      : undefined
                            }
                            onClick={() => setTeamRole(row, null)}
                            data-attr="signals-codeowners-role-mapping-clear"
                        />
                    </Tooltip>
                )}
            </div>
        </div>
    )
}

function AddMappingRow(): JSX.Element {
    const {
        roles,
        draftTeamHandle,
        draftRoleId,
        addingMapping,
        addMappingDisabledReason,
        canManageMappings,
        defaultGithubOrganization,
    } = useValues(codeownersRoleMappingsLogic)
    const { setDraftTeamHandle, setDraftRoleId, addManualMapping } = useActions(codeownersRoleMappingsLogic)

    const roleOptions = (roles ?? []).map((role) => ({
        value: role.id,
        label: role.name,
    }))

    return (
        <div className="flex flex-wrap items-center gap-1 pt-1">
            <LemonInput
                size="small"
                className="min-w-44 flex-1"
                placeholder={
                    defaultGithubOrganization
                        ? `@${defaultGithubOrganization.toLowerCase()}/team-slug`
                        : '@organization/team-slug'
                }
                value={draftTeamHandle}
                disabledReason={
                    !canManageMappings
                        ? 'Only organization admins can change role mappings'
                        : addingMapping
                          ? 'Saving mapping'
                          : undefined
                }
                onChange={setDraftTeamHandle}
            />
            <LemonSelect
                size="small"
                className="w-48"
                value={draftRoleId}
                options={roleOptions}
                placeholder="PostHog role"
                disabledReason={
                    !canManageMappings
                        ? 'Only organization admins can change role mappings'
                        : addingMapping
                          ? 'Saving mapping'
                          : roleOptions.length === 0
                            ? 'Create a PostHog role first'
                            : undefined
                }
                onChange={(roleId) => setDraftRoleId(roleId)}
            />
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPlus />}
                loading={addingMapping}
                disabledReason={addMappingDisabledReason ?? undefined}
                onClick={addManualMapping}
                data-attr="signals-codeowners-role-mapping-add"
            >
                Add
            </LemonButton>
        </div>
    )
}

function ScanControls(): JSX.Element | null {
    const { githubIntegrations } = useValues(integrationsLogic)
    const { scanResult, scanResultLoading, scanIntegrationId, scanRepository, syncOutcomeLoading, canManageMappings } =
        useValues(codeownersRoleMappingsLogic)
    const { rescanCodeownersTeams, scanSingleRepository, setScanIntegrationId, setScanRepository, syncGithubTeams } =
        useActions(codeownersRoleMappingsLogic)

    if (githubIntegrations.length === 0) {
        return null
    }

    const effectiveIntegrationId = scanIntegrationId ?? githubIntegrations[0]?.id ?? null
    const hasUnscannedRepos =
        scanResult !== null && scanResult.total_repository_count > scanResult.scanned_repository_count

    return (
        <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-tertiary">
                {scanResult !== null && scanResult.total_repository_count > 0 && (
                    <span>
                        <span>Scanned CODEOWNERS in&nbsp;</span>
                        <span translate="no">{scanResult.scanned_repository_count}</span>
                        {hasUnscannedRepos && (
                            <>
                                <span>&nbsp;of&nbsp;</span>
                                <span translate="no">{scanResult.total_repository_count}</span>
                            </>
                        )}
                        <span>{scanResult.total_repository_count === 1 ? ' repository.' : ' repositories.'}</span>
                    </span>
                )}
            </div>
            <div className="flex flex-wrap items-center gap-1">
                {hasUnscannedRepos && effectiveIntegrationId !== null && (
                    <>
                        {githubIntegrations.length > 1 && (
                            <LemonSelect
                                size="xsmall"
                                value={effectiveIntegrationId}
                                disabledReason={scanResultLoading ? 'Scanning CODEOWNERS' : undefined}
                                options={githubIntegrations.map((integration) => ({
                                    value: integration.id,
                                    label: integration.display_name,
                                }))}
                                onChange={(next) => setScanIntegrationId(next)}
                            />
                        )}
                        <GitHubRepositoryCombobox
                            integrationId={effectiveIntegrationId}
                            value={scanRepository}
                            disabled={scanResultLoading}
                            placeholder="Scan another repository"
                            onChange={(repo) => {
                                const selected = repo ?? ''
                                setScanRepository(selected)
                                if (selected) {
                                    scanSingleRepository({ repository: selected })
                                }
                            }}
                        />
                    </>
                )}
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={syncOutcomeLoading}
                    disabledReason={!canManageMappings ? 'Only organization admins can sync GitHub teams' : undefined}
                    onClick={syncGithubTeams}
                    data-attr="signals-github-teams-sync-now"
                >
                    Sync GitHub teams
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={scanResultLoading}
                    onClick={rescanCodeownersTeams}
                    data-attr="signals-codeowners-teams-rescan"
                >
                    Rescan CODEOWNERS
                </LemonButton>
            </div>
        </div>
    )
}

export function CodeownersRoleMappings(): JSX.Element {
    const { githubIntegrations } = useValues(integrationsLogic)
    const { roles, rows, initialLoading, loadError, syncOutcome } = useValues(codeownersRoleMappingsLogic)
    const { reloadAll } = useActions(codeownersRoleMappingsLogic)
    const pagination = usePagination(rows, { pageSize: MAPPINGS_PAGE_SIZE, useUrl: false })
    const hasGitHub = githubIntegrations.length > 0

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-3">
            <div className="flex flex-col gap-0.5">
                <h4 className="m-0 text-xs font-semibold text-default">GitHub team role sync</h4>
                <p className="m-0 max-w-2xl text-[11px] leading-snug text-tertiary">
                    Sync GitHub organization teams into PostHog roles so agents and features can resolve team ownership
                    and members. Roles created from GitHub stay in sync automatically, while pre-existing PostHog roles
                    ask before changing members.
                </p>
            </div>
            {initialLoading ? (
                <LemonSkeleton className="h-8 w-full rounded" />
            ) : loadError ? (
                <div className="flex flex-wrap items-center gap-2">
                    <p className="m-0 text-xs text-secondary">Couldn't load GitHub team role mappings.</p>
                    <LemonButton size="xsmall" type="secondary" onClick={reloadAll}>
                        Try again
                    </LemonButton>
                </div>
            ) : (
                <>
                    <ScanControls />
                    {syncOutcome?.skipped_missing_members_permission && (
                        <LemonBanner type="warning">
                            Your GitHub App installation needs organization Members: Read permission to sync team
                            rosters automatically. You can still map CODEOWNERS teams to PostHog roles manually below.
                        </LemonBanner>
                    )}
                    {roles !== null && roles.length === 0 && (
                        <p className="m-0 text-xs text-secondary">
                            No PostHog roles exist in this organization yet.{' '}
                            {hasGitHub ? 'Sync GitHub teams above or ' : 'Connect GitHub above to sync teams or '}
                            <Link to={urls.settings('organization-roles')}>create roles in organization settings</Link>.
                        </p>
                    )}
                    {rows.length === 0 ? (
                        <p className="m-0 text-[11px] leading-snug text-tertiary">
                            {hasGitHub
                                ? 'No GitHub teams synced or found in CODEOWNERS yet. Click Sync GitHub teams above or add a mapping below.'
                                : 'No GitHub teams mapped yet. Connect GitHub above to sync organization teams, or add a mapping below.'}
                        </p>
                    ) : (
                        <div className="flex flex-col gap-1">
                            {pagination.dataSourcePage.map((row) => (
                                <MappingRow key={row.key} row={row} />
                            ))}
                            <PaginationControl {...pagination} nouns={['team', 'teams']} />
                        </div>
                    )}
                    <AddMappingRow />
                </>
            )}
        </div>
    )
}
