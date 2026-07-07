import { useActions, useValues } from 'kea'

import { IconEye } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { truncate } from 'lib/utils/strings'

import {
    CACHE_LABELS,
    featureFlagsStaffToolsLogic,
    StaffCacheEntryStatus,
    StaffCacheKind,
    StaffReadableCacheKind,
    StaffTeamResult,
} from './featureFlagsStaffToolsLogic'
import { StaffCacheEntryModal } from './StaffCacheEntryModal'
import { StaffTeamSearchInput } from './StaffTeamSearchInput'

const NO_SELECTION_REASON = 'Select at least one team'

const ALL_CACHES: StaffCacheKind[] = ['evaluation', 'definitions']

const READABLE_CACHE_KINDS: StaffReadableCacheKind[] = ['evaluation', 'definitions', 'definitions_no_cohorts']

function CacheStatusCell({ status, onView }: { status?: StaffCacheEntryStatus; onView: () => void }): JSX.Element {
    const tag = !status ? (
        <LemonTag type="muted">Unknown</LemonTag>
    ) : status.source !== 'redis' ? (
        <LemonTag type="warning">Miss</LemonTag>
    ) : (
        <>
            <LemonTag type="success">Redis</LemonTag>
            <span className="text-secondary">{status.flag_count} flags</span>
        </>
    )
    return (
        <span className="flex items-center gap-2">
            {tag}
            <LemonButton size="small" icon={<IconEye />} onClick={onView} tooltip="View cache entry" noPadding />
        </span>
    )
}

export function StaffCacheToolsTab(): JSX.Element {
    const {
        selectedTeams,
        selectedTeamIds,
        cacheStatusByTeamId,
        cacheStatusLoading,
        rebuildResultLoading,
        clearResultLoading,
    } = useValues(featureFlagsStaffToolsLogic)
    const { rebuildCache, clearCache, loadCacheStatus, viewCacheEntry } = useActions(featureFlagsStaffToolsLogic)

    const hasSelection = selectedTeamIds.length > 0
    const mutating = rebuildResultLoading || clearResultLoading
    const disabledReason = !hasSelection ? NO_SELECTION_REASON : mutating ? 'Action in progress' : undefined

    const columns: LemonTableColumns<StaffTeamResult> = [
        {
            title: 'Team',
            key: 'team',
            render: (_, team) => (
                <span>
                    {team.name} <span className="text-secondary">(#{team.id})</span>
                </span>
            ),
        },
        {
            title: 'Organization',
            dataIndex: 'organization_name',
        },
        {
            title: 'Project token',
            dataIndex: 'api_token',
            render: (token) => (
                <CopyToClipboardInline
                    explicitValue={String(token)}
                    description="project token"
                    tooltipMessage="Copy project token"
                    iconSize="xsmall"
                    className="font-mono text-xs"
                >
                    {truncate(String(token), 16)}
                </CopyToClipboardInline>
            ),
        },
        ...READABLE_CACHE_KINDS.map((cacheKind) => ({
            title: CACHE_LABELS[cacheKind],
            key: cacheKind,
            render: (_: unknown, team: StaffTeamResult) => (
                <CacheStatusCell
                    status={cacheStatusByTeamId[team.id]?.[cacheKind]}
                    onView={() => viewCacheEntry({ teamId: team.id, cache: cacheKind })}
                />
            ),
        })),
    ]

    return (
        <div className="space-y-4">
            <StaffTeamSearchInput />

            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => rebuildCache({ caches: ALL_CACHES })}
                    disabledReason={disabledReason}
                    loading={rebuildResultLoading}
                >
                    Rebuild flag caches
                </LemonButton>
                <LemonButton
                    status="danger"
                    type="secondary"
                    size="small"
                    onClick={() => clearCache({ caches: ALL_CACHES })}
                    disabledReason={disabledReason}
                    loading={clearResultLoading}
                >
                    Clear caches
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => loadCacheStatus()}
                    disabledReason={!hasSelection ? NO_SELECTION_REASON : undefined}
                    className="ml-auto"
                >
                    Refresh status
                </LemonButton>
            </div>

            <LemonTable
                dataSource={selectedTeams}
                columns={columns}
                loading={cacheStatusLoading}
                rowKey={(team) => team.id}
                emptyState="Search for and select one or more teams to inspect and rebuild their flag caches."
            />

            <StaffCacheEntryModal />
        </div>
    )
}
