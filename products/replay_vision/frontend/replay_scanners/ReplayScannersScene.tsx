import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPencil, IconRefresh, IconSearch, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSwitch,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { VisionDocsLink } from '../components/DocsLink'
import { FilterPill } from '../components/FilterPill'
import { IngestionLimitBanner } from '../components/IngestionLimitBanner'
import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { ScannerTypeBadge } from '../components/ScannerTypeBadge'
import { replayVisionEmptyState } from '../emptyState/replayVisionEmptyState'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { getReplayVisionDeleteDisabledReason, getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { creditsToUsd, formatCreditCount } from '../utils/credits'
import { CreateScannerButton } from './components/CreateScannerButton'
import { VisionMetrics } from './components/VisionMetrics'
import { VisionUsageTab } from './components/VisionUsageTab'
import { type ScannersSorting, SCANNERS_PAGE_SIZE, replayScannersLogic } from './replayScannersLogic'
import { LIMIT_REACHED_TOOLTIP } from './scannerCopy'
import { ENABLED_OPTIONS, EnabledFilter, SCANNER_TYPE_OPTIONS, ScannerType, ReplayScanner } from './types'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

export const scene: SceneExport = {
    component: ReplayScannersScene,
    logic: replayScannersLogic,
    productKey: ProductKey.REPLAY_VISION,
    emptyState: replayVisionEmptyState,
}

export function ReplayScannersScene(): JSX.Element {
    const {
        scanners,
        scannersLoading,
        scannersPage,
        scannersTotal,
        scannersSort,
        togglingIds,
        deletingIds,
        search,
        enabledFilter,
        scannerTypeFilter,
        createdByFilter,
        createdByOptions,
        tagsFilter,
        tagOptions,
        hasActiveFilters,
        scannerStats,
        scannerStatsLoading,
    } = useValues(replayScannersLogic)
    const { loadScanners, deleteScanner, toggleScannerEnabled, setScannersFilters, clearFilters } =
        useActions(replayScannersLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const { showUsd } = useValues(visionQuotaLogic)

    const columns: LemonTableColumns<ReplayScanner> = [
        {
            title: 'Name',
            key: 'name',
            sorter: true,
            render: (_, scanner) => (
                <div className="flex flex-col">
                    <Link to={urls.replayVision(scanner.id)} className="font-semibold text-primary">
                        {scanner.name || '(untitled)'}
                    </Link>
                    {scanner.description && <div className="text-muted text-sm">{scanner.description}</div>}
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, scanner) => (
                <div className="flex items-center gap-2">
                    <LemonSwitch
                        checked={scanner.enabled}
                        onChange={() => toggleScannerEnabled(scanner.id)}
                        disabledReason={
                            togglingIds.includes(scanner.id)
                                ? 'Updating…'
                                : getReplayVisionEditDisabledReason(scanner.user_access_level)
                        }
                        size="small"
                        data-attr="vision-scanner-toggle-enabled"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                        data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
                    />
                    <span className={`inline-block min-w-[4.5rem] ${scanner.enabled ? 'text-success' : 'text-muted'}`}>
                        {scanner.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                    {scanner.limit_reached && (
                        <Tooltip title={LIMIT_REACHED_TOOLTIP}>
                            <LemonTag type="danger">Limit reached</LemonTag>
                        </Tooltip>
                    )}
                </div>
            ),
            sorter: true,
        },
        {
            title: 'Type',
            key: 'scanner_type',
            render: (_, scanner) => <ScannerTypeBadge scannerType={scanner.scanner_type} />,
            sorter: true,
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, scanner) =>
                scanner.tags.length > 0 ? (
                    <ObjectTags
                        tags={scanner.tags}
                        staticOnly
                        onTagClick={(tag) => setScannersFilters({ tagsFilter: [tag] })}
                        data-attr="vision-scanner-row-tags"
                    />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Sampling',
            key: 'sampling_rate',
            render: (_, scanner) => (
                <span className="text-sm tabular-nums">
                    {(scanner.sampling_rate * 100).toFixed(scanner.sampling_rate < 0.1 ? 2 : 1)}%
                </span>
            ),
            sorter: true,
        },
        {
            title: 'Spend this period',
            key: 'credits_this_month',
            render: (_, scanner) => (
                <div className="text-sm tabular-nums">
                    <div>{formatCreditCount(scanner.credits_this_month)}</div>
                    {showUsd && <div className="text-muted text-xs">≈ {creditsToUsd(scanner.credits_this_month)}</div>}
                </div>
            ),
            sorter: true,
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, scanner) =>
                scanner.created_by ? (
                    <ProfilePicture user={scanner.created_by} size="md" showName />
                ) : (
                    <span className="text-muted">—</span>
                ),
            sorter: true,
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, scanner) => (
                <div className="flex gap-1">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPencil />}
                        to={urls.replayVision(scanner.id)}
                        disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                        tooltip="Edit"
                        data-attr="vision-scanner-edit-row"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        loading={deletingIds.includes(scanner.id)}
                        disabledReason={
                            deletingIds.includes(scanner.id)
                                ? 'Deleting…'
                                : getReplayVisionDeleteDisabledReason(scanner.user_access_level)
                        }
                        onClick={() =>
                            LemonDialog.open({
                                title: `Delete "${scanner.name || 'Untitled scanner'}"?`,
                                description: 'This cannot be undone.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteScanner(scanner.id),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        tooltip="Delete"
                        data-attr="vision-scanner-delete"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    />
                </div>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Replay vision"
                description="Set up AI scanners that automatically analyze new session recordings as they come in. Each result emits a queryable event."
                resourceType={{ type: 'replay_vision' }}
                actions={
                    <>
                        <ReplayVisionFeedbackButton />
                        <CreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />
                    </>
                }
            />

            <IngestionLimitBanner />

            {(scannerStats?.total ?? 0) - (scannerStats?.enabled ?? 0) > 0 && (
                <LemonBanner type="warning" dismissKey="replay-vision-launch-beta-scanners">
                    Replay vision is out of beta and scans now use billed credits. Your scanners were turned off for the
                    launch, so re-enable the ones you want to keep running. See{' '}
                    <VisionDocsLink page="quota-and-limits" dataAttr="vision-docs-link-launch-banner">
                        how credits are priced
                    </VisionDocsLink>{' '}
                    in the docs, or check the Usage tab for current spend.
                </LemonBanner>
            )}

            <LemonTabs
                activeKey={searchParams.tab === 'usage' ? 'usage' : 'scanners'}
                onChange={(tab) => push(urls.replayVision(), tab === 'usage' ? { tab } : {})}
                tabs={[
                    { key: 'scanners', label: 'Scanners', content: <></> },
                    { key: 'usage', label: 'Usage', content: <></> },
                ]}
            />

            {searchParams.tab === 'usage' ? (
                <VisionUsageTab />
            ) : (
                <>
                    {(scannerStats?.total ?? 0) > 0 ? (
                        <VisionMetrics />
                    ) : scannerStatsLoading ? (
                        <div className="flex items-center justify-center h-72 bg-bg-light rounded">
                            <Spinner className="text-2xl" />
                        </div>
                    ) : null}

                    <div className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-semibold text-base m-0">Scanners</h3>
                            <div className="ml-auto flex flex-wrap items-center gap-2">
                                <LemonInput
                                    type="search"
                                    placeholder="Search scanners..."
                                    value={search}
                                    onChange={(v) => setScannersFilters({ search: v })}
                                    prefix={<IconSearch />}
                                    className="max-w-sm"
                                />
                                <FilterPill<EnabledFilter>
                                    label="Status"
                                    options={ENABLED_OPTIONS}
                                    value={enabledFilter}
                                    onChange={(v) => setScannersFilters({ enabledFilter: v })}
                                />
                                <FilterPill<ScannerType>
                                    label="Type"
                                    options={TYPE_OPTIONS}
                                    value={scannerTypeFilter}
                                    onChange={(v) => setScannersFilters({ scannerTypeFilter: v })}
                                />
                                <FilterPill<string>
                                    label="Created by"
                                    options={createdByOptions}
                                    value={createdByFilter}
                                    onChange={(v) => setScannersFilters({ createdByFilter: v })}
                                />
                                <FilterPill<string>
                                    label="Tags"
                                    searchable
                                    options={tagOptions}
                                    value={tagsFilter}
                                    onChange={(v) => setScannersFilters({ tagsFilter: v })}
                                />
                                {hasActiveFilters && (
                                    <LemonButton type="tertiary" size="small" onClick={() => clearFilters()}>
                                        Clear filters
                                    </LemonButton>
                                )}
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconRefresh />}
                                    tooltip="Refresh"
                                    onClick={() => loadScanners()}
                                    loading={scannersLoading}
                                />
                            </div>
                        </div>

                        <LemonTable
                            columns={columns}
                            dataSource={scanners}
                            loading={scannersLoading}
                            rowKey="id"
                            pagination={{
                                controlled: true,
                                pageSize: SCANNERS_PAGE_SIZE,
                                currentPage: scannersPage,
                                entryCount: scannersTotal,
                                onForward: () => setScannersFilters({ page: scannersPage + 1 }),
                                onBackward: () => setScannersFilters({ page: scannersPage - 1 }),
                            }}
                            sorting={scannersSort}
                            onSort={(next) => setScannersFilters({ sort: next as ScannersSorting | null })}
                            noSortingCancellation
                            useURLForSorting={false}
                            nouns={['scanner', 'scanners']}
                            emptyState={
                                scannersTotal === 0 && !hasActiveFilters ? (
                                    <div className="flex flex-col items-center gap-3 p-8 text-center">
                                        <div className="text-muted">No scanners yet.</div>
                                        <CreateScannerButton
                                            acceptedLabel="Create your first scanner"
                                            dataAttr="vision-scanner-create-empty"
                                            size="medium"
                                        />
                                        <VisionDocsLink
                                            page="creating-scanners"
                                            dataAttr="vision-empty-docs-link-scanners"
                                        >
                                            Learn how scanners work
                                        </VisionDocsLink>
                                    </div>
                                ) : (
                                    <span className="text-muted">No scanners match your filters.</span>
                                )
                            }
                        />
                    </div>
                </>
            )}
        </SceneContent>
    )
}

export default ReplayScannersScene
