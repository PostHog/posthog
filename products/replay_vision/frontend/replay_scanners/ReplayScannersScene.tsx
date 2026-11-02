import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import * as explorerPng from '@posthog/brand/hoggies/png/explorer'
import { IconRefresh, IconSearch } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonTable,
    LemonTabs,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { pngHoggie } from 'lib/brand/hoggies'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { ObservationSearch } from '../search/ObservationSearch'
import { getReplayVisionDeleteDisabledReason, getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { HIGHLIGHTS_TAB } from '../utils/breadcrumbs'
import { creditsToUsd, formatCreditCount } from '../utils/credits'
import { quotaBannerState } from '../utils/quotaProjection'
import { CreateScannerButton } from './components/CreateScannerButton'
import { HighlightFeedTab } from './components/HighlightFeedTab'
import { QuillCreateScannerButton } from './components/QuillCreateScannerButton'
import { ScannerStatusLabel } from './components/ScannerStatusLabel'
import { VisionMetrics } from './components/VisionMetrics'
import { VisionUsageTab } from './components/VisionUsageTab'
import { ReplayScannerTab } from './replayScannerSceneLogic'
import { type ScannersSorting, SCANNERS_PAGE_SIZE, replayScannersLogic } from './replayScannersLogic'
import { limitReachedTooltip } from './scannerCopy'
import { scannerStatus } from './scannerStatus'
import { ENABLED_OPTIONS, EnabledFilter, scannerTypeOptions, ScannerType, ReplayScanner } from './types'

const HedgehogExplorer = pngHoggie(explorerPng)

function ScannerRowActions({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { deletingIds } = useValues(replayScannersLogic)
    const { deleteScanner, duplicateScanner } = useActions(replayScannersLogic)

    return (
        <More
            data-attr="vision-scanner-row-more"
            overlay={
                <>
                    <LemonButton
                        fullWidth
                        to={urls.replayVision(scanner.id)}
                        disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                        data-attr="vision-scanner-edit-row"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Edit
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        onClick={() => duplicateScanner(scanner.id)}
                        // Duplicating creates a new scanner, so gate on resource-level edit access
                        // rather than this row's per-object level.
                        disabledReason={getReplayVisionEditDisabledReason()}
                        data-attr="vision-scanner-duplicate"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Duplicate
                    </LemonButton>
                    <LemonDivider />
                    <LemonButton
                        fullWidth
                        status="danger"
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
                        data-attr="vision-scanner-delete"
                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    >
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}

// Pinned: a localStorage key. Renaming it shows the banner again to everyone who closed it.
const FIELD_GUIDE_DISMISS_KEY = 'replay-vision-field-guide-callout'

function FieldGuideBanner(): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: FIELD_GUIDE_DISMISS_KEY }))

    // A dismissed LemonBanner renders null but the viewed tracker would still fire, skewing impressions
    if (isDismissed) {
        return null
    }

    return (
        <PostHogCaptureOnViewed name="replay-vision-field-guide-banner-shown">
            <LemonBanner
                type="info"
                dismissKey={FIELD_GUIDE_DISMISS_KEY}
                onClose={() => posthog.capture('replay-vision-field-guide-banner-dismissed')}
                // Negative margins let the hog overflow the banner edges without making the banner taller.
                // z-10 draws it over the border of a banner above. It hides in a narrow banner to keep the text width.
                icon={
                    <HedgehogExplorer className="hidden @lg:block pointer-events-none relative z-10 w-36 h-36 -mt-16 -mb-14 shrink-0" />
                }
            >
                <p>
                    <span className="font-semibold">Meet the 10 species living in your replays.</span> A naturalist's{' '}
                    <Link
                        to="https://posthog.com/field-guide"
                        target="_blank"
                        data-attr="replay-vision-field-guide-banner-link"
                    >
                        field guide
                    </Link>{' '}
                    to the rage-clickers, tab-hoppers, and other wild users you'll spot in user recordings.
                </p>
            </LemonBanner>
        </PostHogCaptureOnViewed>
    )
}

const KNOWN_TABS: string[] = [HIGHLIGHTS_TAB, 'scanners', ReplayScannerTab.Search, 'usage']
const DEFAULT_TAB = HIGHLIGHTS_TAB

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
    const { loadScanners, setScannersFilters, clearFilters } = useActions(replayScannersLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const { showUsd, quota } = useValues(visionQuotaLogic)
    const quotaExhausted = quotaBannerState(quota).kind === 'exhausted'
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const activeTab = KNOWN_TABS.includes(searchParams.tab) ? searchParams.tab : DEFAULT_TAB

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
                    {/* The creator's own description wins; the question fills in for scanners that have none. */}
                    {(scanner.description || scanner.prompt_question) && (
                        <div className="text-muted text-sm">{scanner.description || scanner.prompt_question}</div>
                    )}
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, scanner) => {
                const status = scannerStatus(scanner, { quotaExhausted, drought: null })
                const tooltip =
                    status.kind === 'limit_reached'
                        ? limitReachedTooltip(scanner)
                        : status.kind === 'quota_exhausted'
                          ? "Your organization's Replay Vision credits are used up for this billing period."
                          : null
                return (
                    <Tooltip title={tooltip}>
                        {/* The tooltip attaches its trigger to a DOM element, which the label component is not. */}
                        <span>
                            <ScannerStatusLabel status={status} className="whitespace-nowrap" />
                        </span>
                    </Tooltip>
                )
            },
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
            key: 'actions',
            width: 0,
            render: (_, scanner) => <ScannerRowActions scanner={scanner} />,
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
                        {todayRailNav ? (
                            <QuillCreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />
                        ) : (
                            <CreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />
                        )}
                    </>
                }
            />

            <IngestionLimitBanner />

            <FieldGuideBanner />

            <LemonTabs
                activeKey={activeTab}
                onChange={(tab) => push(urls.replayVision(), tab === DEFAULT_TAB ? {} : { tab })}
                tabs={[
                    {
                        key: HIGHLIGHTS_TAB,
                        label: 'Highlights',
                        content: <></>,
                    },
                    { key: 'scanners', label: 'Scanners', content: <></> },
                    { key: ReplayScannerTab.Search, label: 'Search', content: <></> },
                    { key: 'usage', label: 'Usage', content: <></> },
                ]}
            />

            {activeTab === HIGHLIGHTS_TAB ? (
                <HighlightFeedTab />
            ) : activeTab === ReplayScannerTab.Search ? (
                <ObservationSearch className="mt-2 w-4/5 mx-auto" />
            ) : activeTab === 'usage' ? (
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
                                    dataAttr="vision-scanners-status-filter"
                                    options={ENABLED_OPTIONS}
                                    value={enabledFilter}
                                    onChange={(v) => setScannersFilters({ enabledFilter: v })}
                                />
                                <FilterPill<ScannerType>
                                    label="Type"
                                    dataAttr="vision-scanners-type-filter"
                                    options={scannerTypeOptions(
                                        !!featureFlags[FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER] ||
                                            !!scannerStats?.by_type?.experiment?.total
                                    ).map(({ value, label }) => ({ value, label }))}
                                    value={scannerTypeFilter}
                                    onChange={(v) => setScannersFilters({ scannerTypeFilter: v })}
                                />
                                <FilterPill<string>
                                    label="Created by"
                                    dataAttr="vision-scanners-created-by-filter"
                                    options={createdByOptions}
                                    value={createdByFilter}
                                    onChange={(v) => setScannersFilters({ createdByFilter: v })}
                                />
                                <FilterPill<string>
                                    label="Tags"
                                    dataAttr="vision-scanners-tags-filter"
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
