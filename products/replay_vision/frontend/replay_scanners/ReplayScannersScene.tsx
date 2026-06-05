import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { XRayHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FilterPill } from '../components/FilterPill'
import { VisionMetrics } from './components/VisionMetrics'
import { type ScannersSorting, SCANNERS_PAGE_SIZE, replayScannersLogic } from './replayScannersLogic'
import {
    ENABLED_OPTIONS,
    EnabledFilter,
    SCANNER_TYPE_OPTIONS,
    SCANNER_TYPE_TAG_TYPE,
    ScannerType,
    ReplayScanner,
    scannerTypeLabel,
} from './types'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

export const scene: SceneExport = {
    component: ReplayScannersScene,
    logic: replayScannersLogic,
    productKey: ProductKey.REPLAY_VISION,
}

export function ReplayScannersScene(): JSX.Element {
    const {
        scanners,
        scannersLoading,
        scannersPage,
        scannersTotal,
        scannersSort,
        togglingIds,
        search,
        enabledFilter,
        scannerTypeFilter,
        createdByFilter,
        createdByOptions,
        hasActiveFilters,
        scannerStats,
    } = useValues(replayScannersLogic)
    const { loadScanners, deleteScanner, duplicateScanner, toggleScannerEnabled, setScannersFilters, clearFilters } =
        useActions(replayScannersLogic)
    const { push } = useActions(router)

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
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch
                            checked={scanner.enabled}
                            onChange={() => toggleScannerEnabled(scanner.id)}
                            disabled={togglingIds.includes(scanner.id)}
                            size="small"
                        />
                    </AccessControlAction>
                    <span className={`inline-block min-w-[4.5rem] ${scanner.enabled ? 'text-success' : 'text-muted'}`}>
                        {scanner.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: true,
        },
        {
            title: 'Type',
            key: 'scanner_type',
            render: (_, scanner) => (
                <LemonTag type={SCANNER_TYPE_TAG_TYPE[scanner.scanner_type]}>
                    {scannerTypeLabel(scanner.scanner_type)}
                </LemonTag>
            ),
            sorter: true,
        },
        {
            title: 'Description',
            key: 'description',
            render: (_, scanner) => (
                <div className="text-sm text-muted truncate max-w-md">
                    {scanner.description || <span className="italic">No description</span>}
                </div>
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
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => push(urls.replayVision(scanner.id))}
                            tooltip="Edit"
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => duplicateScanner(scanner.id)}
                            tooltip="Duplicate"
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
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
                        />
                    </AccessControlAction>
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
            />

            <ProductIntroduction
                productName="Replay vision"
                productKey={ProductKey.REPLAY_VISION}
                thingName="scanner"
                description="Replay vision runs scanners over your completed sessions on a schedule or on demand. Describe what you want to look for and the model watches each recording for it — categorizing sessions, scoring intent, flagging bugs, or detecting any pattern you can put into a prompt. Each result lands as a queryable event you can build insights, alerts, and cohorts on."
                secondaryDescription="Start from a template or build a fully custom scanner."
                customHog={XRayHog}
                action={() => push(urls.replayVisionTemplates())}
            />

            {(scannerStats?.total ?? 0) > 0 && <VisionMetrics />}

            <SceneSection
                title="Scanners"
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            to={urls.replayVisionTemplates()}
                            data-attr="create-replay-scanner"
                        >
                            New scanner
                        </LemonButton>
                    </AccessControlAction>
                }
            >
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search scanners..."
                        value={search}
                        onChange={(v) => setScannersFilters({ search: v })}
                        prefix={<IconSearch />}
                        className="max-w-sm"
                    />
                    <div className="ml-auto flex flex-wrap items-center gap-2">
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
                        {hasActiveFilters && (
                            <LemonButton type="tertiary" size="small" onClick={() => clearFilters()}>
                                Clear filters
                            </LemonButton>
                        )}
                        <LemonButton type="secondary" onClick={() => loadScanners()} size="small">
                            Refresh
                        </LemonButton>
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
                                <LemonButton type="primary" icon={<IconPlus />} to={urls.replayVisionTemplates()}>
                                    Create your first scanner
                                </LemonButton>
                            </div>
                        ) : (
                            <span className="text-muted">No scanners match your filters.</span>
                        )
                    }
                />
            </SceneSection>
        </SceneContent>
    )
}

export default ReplayScannersScene
