import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { OrganizationMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { IntegrationType, OrganizationType } from '~/types'

import {
    roleExternalReferencesApplySyncCreate,
    roleExternalReferencesCreate,
    roleExternalReferencesDestroy,
    roleExternalReferencesList,
    roleExternalReferencesPartialUpdate,
    roleExternalReferencesSyncGithubCreate,
} from 'products/integrations/frontend/generated/api'
import type {
    GitHubRoleSyncResponseApi,
    RoleExternalReferenceApi,
    RoleSyncActionModeEnumApi,
} from 'products/integrations/frontend/generated/api.schemas'
import { rolesList } from 'products/platform_features/frontend/generated/api'
import type { RoleApi } from 'products/platform_features/frontend/generated/api.schemas'
import { signalsCodeownersTeamsList } from 'products/signals/frontend/generated/api'
import type { CodeownersTeamApi, CodeownersTeamsResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { captureInboxSettingsChanged } from '../inboxAnalytics'

const GITHUB_ORG_RE = /^[a-z0-9][a-z0-9-]{0,38}$/
const GITHUB_SLUG_RE = /^[a-z0-9][a-z0-9._-]*$/

export interface ParsedCodeownersTeamInput {
    providerOrganizationId: string
    teamSlug: string
    handle: string
}

export interface CodeownersRoleMappingRow {
    key: string
    providerOrganizationId: string
    teamSlug: string
    handle: string
    repositories: string[]
    explicitReference: RoleExternalReferenceApi | null
    selectedRoleId: string | null
    suggestedRoleId: string | null
    suggestedRoleName: string | null
}

export function parseCodeownersTeamInput(
    rawInput: string,
    defaultOrganization: string | null
): ParsedCodeownersTeamInput | null {
    const trimmed = rawInput.trim()
    if (!trimmed || trimmed.slice(1).includes('@')) {
        return null
    }
    const withoutAt = trimmed.replace(/^@/, '').trim()
    if (!withoutAt) {
        return null
    }
    let org: string
    let slug: string
    if (withoutAt.includes('/')) {
        const parts = withoutAt.split('/')
        if (parts.length !== 2) {
            return null
        }
        org = parts[0].trim().toLowerCase()
        slug = parts[1].trim().toLowerCase()
    } else if (defaultOrganization) {
        org = defaultOrganization.trim().toLowerCase()
        slug = withoutAt.toLowerCase()
    } else {
        return null
    }
    if (!GITHUB_ORG_RE.test(org) || !GITHUB_SLUG_RE.test(slug)) {
        return null
    }
    return {
        providerOrganizationId: org,
        teamSlug: slug,
        handle: `@${org}/${slug}`,
    }
}

function formatReferenceHandle(ref: RoleExternalReferenceApi): { org: string; slug: string; handle: string } {
    const org = ref.provider_organization_id.trim().toLowerCase()
    const rawSlug = (ref.provider_role_slug ?? '').trim().toLowerCase()
    if (rawSlug) {
        return { org, slug: rawSlug, handle: `@${org}/${rawSlug}` }
    }
    const cleanedName = ref.provider_role_name.trim()
    if (cleanedName.startsWith('@')) {
        const slugPart = cleanedName.split('/')[1]?.trim().toLowerCase() || ref.provider_role_id.trim().toLowerCase()
        return { org, slug: slugPart, handle: cleanedName.toLowerCase() }
    }
    const fallbackSlug =
        cleanedName
            .toLowerCase()
            .replace(/[^a-z0-9._-]+/g, '-')
            .replace(/^-+|-+$/g, '') || ref.provider_role_id.trim().toLowerCase()
    return { org, slug: fallbackSlug, handle: `@${org}/${fallbackSlug}` }
}

export function mergeCodeownersMappingRows(
    scannedTeams: readonly CodeownersTeamApi[],
    references: readonly RoleExternalReferenceApi[]
): CodeownersRoleMappingRow[] {
    const activeRefByKey = new Map<string, RoleExternalReferenceApi>()
    const orphanedRefs: RoleExternalReferenceApi[] = []

    for (const ref of references) {
        if (ref.orphaned_at !== null) {
            orphanedRefs.push(ref)
            continue
        }
        const slug = (ref.provider_role_slug || ref.provider_role_id).trim().toLowerCase()
        if (!slug) {
            continue
        }
        const key = `${ref.provider_organization_id.trim().toLowerCase()}/${slug}`
        activeRefByKey.set(key, ref)
    }

    const rowsByKey = new Map<string, CodeownersRoleMappingRow>()
    for (const scanned of scannedTeams) {
        const org = scanned.provider_organization_id.toLowerCase()
        const slug = scanned.team_slug.toLowerCase()
        const key = `${org}/${slug}`
        const explicitReference = activeRefByKey.get(key) ?? null
        rowsByKey.set(key, {
            key,
            providerOrganizationId: org,
            teamSlug: slug,
            handle: `@${org}/${slug}`,
            repositories: [...scanned.repositories],
            explicitReference,
            selectedRoleId: explicitReference?.role ?? null,
            suggestedRoleId:
                explicitReference === null && scanned.match_source === 'name_match' ? scanned.likely_role_id : null,
            suggestedRoleName:
                explicitReference === null && scanned.match_source === 'name_match' ? scanned.likely_role_name : null,
        })
    }

    for (const [key, ref] of activeRefByKey.entries()) {
        if (rowsByKey.has(key)) {
            continue
        }
        const formatted = formatReferenceHandle(ref)
        rowsByKey.set(key, {
            key,
            providerOrganizationId: formatted.org,
            teamSlug: formatted.slug,
            handle: formatted.handle,
            repositories: [],
            explicitReference: ref,
            selectedRoleId: ref.role,
            suggestedRoleId: null,
            suggestedRoleName: null,
        })
    }

    for (const ref of orphanedRefs) {
        const formatted = formatReferenceHandle(ref)
        const key = `orphaned:${ref.id}`
        rowsByKey.set(key, {
            key,
            providerOrganizationId: formatted.org,
            teamSlug: formatted.slug,
            handle: formatted.handle,
            repositories: [],
            explicitReference: ref,
            selectedRoleId: ref.role,
            suggestedRoleId: null,
            suggestedRoleName: null,
        })
    }

    return Array.from(rowsByKey.values()).sort((a, b) => {
        const aOrphaned = a.explicitReference?.orphaned_at != null ? 1 : 0
        const bOrphaned = b.explicitReference?.orphaned_at != null ? 1 : 0
        if (aOrphaned !== bOrphaned) {
            return aOrphaned - bOrphaned
        }
        return a.handle.localeCompare(b.handle)
    })
}

function mergeScanResponses(
    previous: CodeownersTeamsResponseApi | null,
    incoming: CodeownersTeamsResponseApi
): CodeownersTeamsResponseApi {
    if (!previous) {
        return incoming
    }
    const byKey = new Map<string, CodeownersTeamApi>()
    for (const team of previous.teams) {
        byKey.set(`${team.provider_organization_id}/${team.team_slug}`, team)
    }
    for (const team of incoming.teams) {
        const key = `${team.provider_organization_id}/${team.team_slug}`
        const existing = byKey.get(key)
        const mergedRepos = existing
            ? Array.from(new Set([...existing.repositories, ...team.repositories]))
            : [...team.repositories]
        byKey.set(key, {
            ...team,
            repositories: mergedRepos,
        })
    }
    return {
        teams: Array.from(byKey.values()).sort((a, b) => a.handle.localeCompare(b.handle)),
        scanned_repository_count: Math.max(previous.scanned_repository_count, incoming.scanned_repository_count),
        total_repository_count: Math.max(previous.total_repository_count, incoming.total_repository_count),
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface codeownersRoleMappingsLogicValues {
    githubIntegrations: IntegrationType[] // integrationsLogic
    currentOrganization: OrganizationType | null // organizationLogic
    currentOrganizationId: string // organizationLogic
    currentTeamId: number | null // teamLogic
    addMappingDisabledReason: string | null
    addingMapping: boolean
    canManageMappings: boolean
    defaultGithubOrganization: string | null
    draftRoleId: string | null
    draftTeamHandle: string
    initialLoading: boolean
    loadError: boolean
    parsedDraftTeam: ParsedCodeownersTeamInput | null
    references: RoleExternalReferenceApi[] | null
    referencesLoading: boolean
    roles: RoleApi[] | null
    rolesLoading: boolean
    rows: CodeownersRoleMappingRow[]
    savingTeamKeys: Record<string, boolean>
    scanIntegrationId: number | null
    scanRepository: string
    scanResult: CodeownersTeamsResponseApi | null
    scanResultLoading: boolean
    syncOutcome: GitHubRoleSyncResponseApi | null
    syncOutcomeLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface codeownersRoleMappingsLogicActions {
    addManualMapping: () => {
        value: true
    }
    addManualMappingFinished: (
        references: RoleExternalReferenceApi[] | null,
        succeeded: boolean
    ) => {
        references: RoleExternalReferenceApi[] | null
        succeeded: boolean
    }
    applyReferenceSync: (
        row: CodeownersRoleMappingRow,
        mode: RoleSyncActionModeEnumApi
    ) => {
        mode: RoleSyncActionModeEnumApi
        row: CodeownersRoleMappingRow
    }
    applyReferenceSyncFinished: (
        key: string,
        updated: RoleExternalReferenceApi | null
    ) => {
        key: string
        updated: RoleExternalReferenceApi | null
    }
    loadCodeownersTeams: () => any
    loadCodeownersTeamsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCodeownersTeamsSuccess: (
        scanResult: CodeownersTeamsResponseApi,
        payload?: any
    ) => {
        scanResult: CodeownersTeamsResponseApi
        payload?: any
    }
    loadReferences: () => any
    loadReferencesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReferencesSuccess: (
        references: RoleExternalReferenceApi[],
        payload?: any
    ) => {
        references: RoleExternalReferenceApi[]
        payload?: any
    }
    loadRoles: () => any
    loadRolesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRolesSuccess: (
        roles: RoleApi[],
        payload?: any
    ) => {
        roles: RoleApi[]
        payload?: any
    }
    reloadAll: () => {
        value: true
    }
    rescanCodeownersTeams: () => any
    rescanCodeownersTeamsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    rescanCodeownersTeamsSuccess: (
        scanResult: CodeownersTeamsResponseApi,
        payload?: any
    ) => {
        scanResult: CodeownersTeamsResponseApi
        payload?: any
    }
    scanSingleRepository: ({ repository }: { repository: string }) => {
        repository: string
    }
    scanSingleRepositoryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    scanSingleRepositorySuccess: (
        scanResult: CodeownersTeamsResponseApi | null,
        payload?: {
            repository: string
        }
    ) => {
        scanResult: CodeownersTeamsResponseApi | null
        payload?: {
            repository: string
        }
    }
    setDraftRoleId: (roleId: string | null) => {
        roleId: string | null
    }
    setDraftTeamHandle: (teamHandle: string) => {
        teamHandle: string
    }
    setScanIntegrationId: (integrationId: number | null) => {
        integrationId: number | null
    }
    setScanRepository: (repository: string) => {
        repository: string
    }
    setTeamRole: (
        row: CodeownersRoleMappingRow,
        roleId: string | null
    ) => {
        roleId: string | null
        row: CodeownersRoleMappingRow
    }
    setTeamRoleFinished: (
        key: string,
        references: RoleExternalReferenceApi[] | null
    ) => {
        key: string
        references: RoleExternalReferenceApi[] | null
    }
    syncGithubTeams: () => any
    syncGithubTeamsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    syncGithubTeamsSuccess: (
        syncOutcome: GitHubRoleSyncResponseApi | null,
        payload?: any
    ) => {
        syncOutcome: GitHubRoleSyncResponseApi | null
        payload?: any
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface codeownersRoleMappingsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        canManageMappings: (currentOrganization: any) => boolean
        defaultGithubOrganization: (githubIntegrations: any) => string | null
        initialLoading: (
            roles: any,
            references: any,
            rolesLoading: any,
            referencesLoading: any,
            scanResult: any,
            scanResultLoading: any
        ) => boolean
        rows: (scanResult: any, references: any) => CodeownersRoleMappingRow[]
        parsedDraftTeam: (draftTeamHandle: any, defaultGithubOrganization: any) => ParsedCodeownersTeamInput | null
        addMappingDisabledReason: (
            canManageMappings: any,
            roles: any,
            draftTeamHandle: any,
            parsedDraftTeam: any,
            draftRoleId: any
        ) => string | null
    }
}

export type codeownersRoleMappingsLogicType = MakeLogicType<
    codeownersRoleMappingsLogicValues,
    codeownersRoleMappingsLogicActions,
    Record<string, any>,
    codeownersRoleMappingsLogicMeta
>

export const codeownersRoleMappingsLogic = kea<codeownersRoleMappingsLogicType>([
    path(['products', 'signals', 'frontend', 'inbox', 'logics', 'codeownersRoleMappingsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            organizationLogic,
            ['currentOrganization', 'currentOrganizationId'],
            integrationsLogic,
            ['githubIntegrations'],
        ],
    })),
    actions({
        reloadAll: true,
        setDraftTeamHandle: (teamHandle: string) => ({ teamHandle }),
        setDraftRoleId: (roleId: string | null) => ({ roleId }),
        setScanIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setScanRepository: (repository: string) => ({ repository }),
        setTeamRole: (row: CodeownersRoleMappingRow, roleId: string | null) => ({ row, roleId }),
        setTeamRoleFinished: (key: string, references: RoleExternalReferenceApi[] | null) => ({ key, references }),
        applyReferenceSync: (row: CodeownersRoleMappingRow, mode: RoleSyncActionModeEnumApi) => ({ row, mode }),
        applyReferenceSyncFinished: (key: string, updated: RoleExternalReferenceApi | null) => ({ key, updated }),
        addManualMapping: true,
        addManualMappingFinished: (references: RoleExternalReferenceApi[] | null, succeeded: boolean) => ({
            references,
            succeeded,
        }),
    }),
    loaders(({ values }) => ({
        roles: [
            null as RoleApi[] | null,
            {
                loadRoles: async () => {
                    if (!values.currentOrganizationId) {
                        return []
                    }
                    const response = await rolesList(values.currentOrganizationId)
                    return response.results
                },
            },
        ],
        references: [
            null as RoleExternalReferenceApi[] | null,
            {
                loadReferences: async () => {
                    if (!values.currentOrganizationId) {
                        return []
                    }
                    const response = await roleExternalReferencesList(values.currentOrganizationId, {
                        provider: 'github',
                    })
                    return response.results
                },
            },
        ],
        scanResult: [
            null as CodeownersTeamsResponseApi | null,
            {
                loadCodeownersTeams: async () => {
                    if (values.currentTeamId == null) {
                        return { teams: [], scanned_repository_count: 0, total_repository_count: 0 }
                    }
                    return await signalsCodeownersTeamsList(String(values.currentTeamId))
                },
                rescanCodeownersTeams: async () => {
                    if (values.currentTeamId == null) {
                        return { teams: [], scanned_repository_count: 0, total_repository_count: 0 }
                    }
                    return await signalsCodeownersTeamsList(String(values.currentTeamId))
                },
                scanSingleRepository: async ({ repository }: { repository: string }) => {
                    if (values.currentTeamId == null || !repository) {
                        return values.scanResult
                    }
                    const response = await signalsCodeownersTeamsList(String(values.currentTeamId), { repository })
                    return mergeScanResponses(values.scanResult, response)
                },
            },
        ],
        syncOutcome: [
            null as GitHubRoleSyncResponseApi | null,
            {
                syncGithubTeams: async () => {
                    if (!values.currentOrganizationId) {
                        return null
                    }
                    return await roleExternalReferencesSyncGithubCreate(values.currentOrganizationId)
                },
            },
        ],
    })),
    reducers({
        references: {
            setTeamRoleFinished: (state, { references }) => references ?? state,
            addManualMappingFinished: (state, { references }) => references ?? state,
            applyReferenceSyncFinished: (state, { updated }) =>
                updated && state ? state.map((item) => (item.id === updated.id ? updated : item)) : state,
        },
        loadError: [
            false,
            {
                loadRoles: () => false,
                loadReferences: () => false,
                loadRolesFailure: () => true,
                loadReferencesFailure: () => true,
            },
        ],
        savingTeamKeys: [
            {} as Record<string, boolean>,
            {
                setTeamRole: (state, { row }) => ({ ...state, [row.key]: true }),
                setTeamRoleFinished: (state, { key }) => {
                    const next = { ...state }
                    delete next[key]
                    return next
                },
                applyReferenceSync: (state, { row }) => ({ ...state, [row.key]: true }),
                applyReferenceSyncFinished: (state, { key }) => {
                    const next = { ...state }
                    delete next[key]
                    return next
                },
            },
        ],
        addingMapping: [
            false,
            {
                addManualMapping: () => true,
                addManualMappingFinished: () => false,
            },
        ],
        draftTeamHandle: [
            '',
            {
                setDraftTeamHandle: (_, { teamHandle }) => teamHandle,
                addManualMappingFinished: (state, { succeeded }) => (succeeded ? '' : state),
            },
        ],
        draftRoleId: [
            null as string | null,
            {
                setDraftRoleId: (_, { roleId }) => roleId,
                addManualMappingFinished: (state, { succeeded }) => (succeeded ? null : state),
            },
        ],
        scanIntegrationId: [
            null as number | null,
            {
                setScanIntegrationId: (_, { integrationId }) => integrationId,
            },
        ],
        scanRepository: [
            '',
            {
                setScanRepository: (_, { repository }) => repository,
                setScanIntegrationId: () => '',
                scanSingleRepositorySuccess: () => '',
            },
        ],
    }),
    selectors({
        canManageMappings: [
            (s) => [s.currentOrganization],
            (currentOrganization: OrganizationType | null): boolean =>
                Boolean(
                    currentOrganization &&
                    (currentOrganization.membership_level ?? 0) >= OrganizationMembershipLevel.Admin
                ),
        ],
        defaultGithubOrganization: [
            (s) => [s.githubIntegrations],
            (githubIntegrations: IntegrationType[]): string | null =>
                githubIntegrations.length === 1 ? githubIntegrations[0].display_name : null,
        ],
        initialLoading: [
            (s) => [s.roles, s.references, s.rolesLoading, s.referencesLoading, s.scanResult, s.scanResultLoading],
            (
                roles: RoleApi[] | null,
                references: RoleExternalReferenceApi[] | null,
                rolesLoading: boolean,
                referencesLoading: boolean,
                scanResult: CodeownersTeamsResponseApi | null,
                scanResultLoading: boolean
            ): boolean =>
                (roles === null && rolesLoading) ||
                (references === null && referencesLoading) ||
                (scanResult === null && scanResultLoading),
        ],
        rows: [
            (s) => [s.scanResult, s.references],
            (
                scanResult: CodeownersTeamsResponseApi | null,
                references: RoleExternalReferenceApi[] | null
            ): CodeownersRoleMappingRow[] => mergeCodeownersMappingRows(scanResult?.teams ?? [], references ?? []),
        ],
        parsedDraftTeam: [
            (s) => [s.draftTeamHandle, s.defaultGithubOrganization],
            (draftTeamHandle: string, defaultGithubOrganization: string | null): ParsedCodeownersTeamInput | null =>
                parseCodeownersTeamInput(draftTeamHandle, defaultGithubOrganization),
        ],
        addMappingDisabledReason: [
            (s) => [s.canManageMappings, s.roles, s.draftTeamHandle, s.parsedDraftTeam, s.draftRoleId],
            (
                canManageMappings: boolean,
                roles: RoleApi[] | null,
                draftTeamHandle: string,
                parsedDraftTeam: ParsedCodeownersTeamInput | null,
                draftRoleId: string | null
            ): string | null => {
                if (!canManageMappings) {
                    return 'Only organization admins can change role mappings'
                }
                if ((roles?.length ?? 0) === 0) {
                    return 'Create a PostHog role in organization settings first'
                }
                if (!draftTeamHandle.trim()) {
                    return 'Enter a GitHub team like @org/team-slug'
                }
                if (!parsedDraftTeam) {
                    return 'Use the @organization/team-slug format'
                }
                if (!draftRoleId) {
                    return 'Pick a PostHog role'
                }
                return null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        reloadAll: () => {
            actions.loadRoles()
            actions.loadReferences()
            actions.loadCodeownersTeams()
        },
        syncGithubTeamsSuccess: ({ syncOutcome }) => {
            actions.reloadAll()
            if (!syncOutcome) {
                return
            }
            if (syncOutcome.skipped_missing_members_permission) {
                lemonToast.warning('GitHub organization Members: Read permission is required to sync teams')
            } else {
                lemonToast.success('Synced GitHub teams with PostHog roles')
            }
            captureInboxSettingsChanged({
                setting: 'github_roles_synced',
                newValue: syncOutcome.created_roles + syncOutcome.updated_roles + syncOutcome.proposed_roles,
                success: !syncOutcome.skipped_missing_members_permission,
                scope: 'team',
            })
        },
        syncGithubTeamsFailure: () => {
            captureInboxSettingsChanged({
                setting: 'github_roles_synced',
                newValue: null,
                success: false,
                scope: 'team',
            })
        },
        rescanCodeownersTeamsSuccess: ({ scanResult }) => {
            if (scanResult) {
                captureInboxSettingsChanged({
                    setting: 'codeowners_teams_scanned',
                    newValue: scanResult.teams.length,
                    success: true,
                    scope: 'team',
                })
            }
        },
        rescanCodeownersTeamsFailure: () => {
            captureInboxSettingsChanged({
                setting: 'codeowners_teams_scanned',
                newValue: null,
                success: false,
                scope: 'team',
            })
        },
        scanSingleRepositorySuccess: ({ scanResult }) => {
            if (scanResult) {
                captureInboxSettingsChanged({
                    setting: 'codeowners_teams_scanned',
                    newValue: scanResult.teams.length,
                    success: true,
                    scope: 'team',
                })
            }
        },
        scanSingleRepositoryFailure: () => {
            captureInboxSettingsChanged({
                setting: 'codeowners_teams_scanned',
                newValue: null,
                success: false,
                scope: 'team',
            })
        },
        applyReferenceSync: async ({ row, mode }) => {
            if (!values.currentOrganizationId || !row.explicitReference) {
                actions.applyReferenceSyncFinished(row.key, null)
                return
            }
            try {
                const updated = await roleExternalReferencesApplySyncCreate(
                    values.currentOrganizationId,
                    row.explicitReference.id,
                    { mode }
                )
                actions.applyReferenceSyncFinished(row.key, updated)
                actions.loadRoles()
                lemonToast.success(
                    mode === 'auto'
                        ? `Keeping ${row.handle} in sync`
                        : mode === 'once'
                          ? `Synced members for ${row.handle}`
                          : `Paused automatic sync for ${row.handle}`
                )
                captureInboxSettingsChanged({
                    setting: 'github_role_sync_mode_updated',
                    newValue: mode,
                    success: true,
                    scope: 'team',
                })
            } catch (error) {
                actions.applyReferenceSyncFinished(row.key, null)
                const detail = (error as { detail?: string })?.detail
                lemonToast.error(detail || "Couldn't update role sync")
                captureInboxSettingsChanged({
                    setting: 'github_role_sync_mode_updated',
                    newValue: mode,
                    success: false,
                    scope: 'team',
                })
            }
        },
        setTeamRole: async ({ row, roleId }) => {
            if (!values.currentOrganizationId) {
                actions.setTeamRoleFinished(row.key, null)
                return
            }
            const currentRefs = values.references ?? []
            try {
                if (roleId === null) {
                    if (!row.explicitReference) {
                        actions.setTeamRoleFinished(row.key, currentRefs)
                        return
                    }
                    await roleExternalReferencesDestroy(values.currentOrganizationId, row.explicitReference.id)
                    const nextRefs = currentRefs.filter((item) => item.id !== row.explicitReference?.id)
                    actions.setTeamRoleFinished(row.key, nextRefs)
                    captureInboxSettingsChanged({
                        setting: 'codeowners_role_mapping_removed',
                        newValue: null,
                        success: true,
                        scope: 'team',
                    })
                    actions.loadCodeownersTeams()
                    return
                }

                if (row.explicitReference) {
                    const updated = await roleExternalReferencesPartialUpdate(
                        values.currentOrganizationId,
                        row.explicitReference.id,
                        { role: roleId }
                    )
                    const nextRefs = currentRefs.map((item) => (item.id === updated.id ? updated : item))
                    actions.setTeamRoleFinished(row.key, nextRefs)
                } else {
                    const created = await roleExternalReferencesCreate(values.currentOrganizationId, {
                        provider: 'github',
                        provider_organization_id: row.providerOrganizationId,
                        provider_role_id: row.teamSlug,
                        provider_role_slug: row.teamSlug,
                        provider_role_name: row.handle,
                        role: roleId,
                    })
                    actions.setTeamRoleFinished(row.key, [...currentRefs, created])
                }
                captureInboxSettingsChanged({
                    setting: 'codeowners_role_mapping_saved',
                    newValue: null,
                    success: true,
                    scope: 'team',
                })
            } catch (error) {
                actions.setTeamRoleFinished(row.key, null)
                const detail = (error as { detail?: string })?.detail
                lemonToast.error(
                    detail || (roleId === null ? "Couldn't remove role mapping" : "Couldn't save role mapping")
                )
                captureInboxSettingsChanged({
                    setting: roleId === null ? 'codeowners_role_mapping_removed' : 'codeowners_role_mapping_saved',
                    newValue: null,
                    success: false,
                    scope: 'team',
                })
            }
        },
        addManualMapping: async () => {
            const parsed = values.parsedDraftTeam
            const roleId = values.draftRoleId
            if (!values.currentOrganizationId || !parsed || !roleId) {
                actions.addManualMappingFinished(null, false)
                return
            }
            const currentRefs = values.references ?? []
            const existing = currentRefs.find(
                (item) =>
                    item.orphaned_at === null &&
                    item.provider_organization_id.toLowerCase() === parsed.providerOrganizationId &&
                    (item.provider_role_slug || item.provider_role_id).toLowerCase() === parsed.teamSlug
            )
            try {
                if (existing) {
                    const updated = await roleExternalReferencesPartialUpdate(
                        values.currentOrganizationId,
                        existing.id,
                        { role: roleId }
                    )
                    actions.addManualMappingFinished(
                        currentRefs.map((item) => (item.id === updated.id ? updated : item)),
                        true
                    )
                } else {
                    const created = await roleExternalReferencesCreate(values.currentOrganizationId, {
                        provider: 'github',
                        provider_organization_id: parsed.providerOrganizationId,
                        provider_role_id: parsed.teamSlug,
                        provider_role_slug: parsed.teamSlug,
                        provider_role_name: parsed.handle,
                        role: roleId,
                    })
                    actions.addManualMappingFinished([...currentRefs, created], true)
                }
                captureInboxSettingsChanged({
                    setting: 'codeowners_role_mapping_saved',
                    newValue: null,
                    success: true,
                    scope: 'team',
                })
            } catch (error) {
                actions.addManualMappingFinished(null, false)
                const detail = (error as { detail?: string })?.detail
                lemonToast.error(detail || "Couldn't save role mapping")
                captureInboxSettingsChanged({
                    setting: 'codeowners_role_mapping_saved',
                    newValue: null,
                    success: false,
                    scope: 'team',
                })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.reloadAll()
    }),
])
