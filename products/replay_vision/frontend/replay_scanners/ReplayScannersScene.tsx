import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconEye, IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonButtonWithDropdown,
    LemonCheckbox,
    LemonInput,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { VisionQuotaMeter } from './components/VisionQuotaMeter'
import { replayScannersLogic } from './replayScannersLogic'
import { ENABLED_OPTIONS, EnabledFilter, SCANNER_TYPE_OPTIONS, ScannerType, ReplayScanner } from './types'

const TYPE_OPTIONS: { value: ScannerType; label: string }[] = SCANNER_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

export const scene: SceneExport = {
    component: ReplayScannersScene,
    logic: replayScannersLogic,
    productKey: ProductKey.REPLAY_VISION,
}

function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
}: {
    label: string
    options: { value: T; label: string }[]
    value: T[]
    onChange: (next: T[]) => void
}): JSX.Element {
    const toggle = (v: T): void => {
        onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
    }
    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            dropdown={{
                closeOnClickInside: false,
                overlay: options.map((opt) => (
                    <LemonButton key={opt.value} fullWidth onClick={() => toggle(opt.value)}>
                        <LemonCheckbox checked={value.includes(opt.value)} className="pointer-events-none mr-2" />
                        {opt.label}
                    </LemonButton>
                )),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}

export function ReplayScannersScene(): JSX.Element {
    const { filteredScanners, scanners, scannersLoading, search, enabledFilter, scannerTypeFilter, hasActiveFilters } =
        useValues(replayScannersLogic)
    const {
        loadScanners,
        deleteScanner,
        duplicateScanner,
        toggleScannerEnabled,
        setSearch,
        setEnabledFilter,
        setScannerTypeFilter,
        clearFilters,
    } = useActions(replayScannersLogic)
    const { push } = useActions(router)

    const columns: LemonTableColumns<ReplayScanner> = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name),
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
                            size="small"
                        />
                    </AccessControlAction>
                    <span className={scanner.enabled ? 'text-success' : 'text-muted'}>
                        {scanner.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Type',
            key: 'scanner_type',
            render: (_, scanner) => <LemonTag type="option">{scanner.scanner_type}</LemonTag>,
            sorter: (a, b) => a.scanner_type.localeCompare(b.scanner_type),
        },
        {
            title: 'Config',
            key: 'config',
            width: '40%',
            render: (_, scanner) => (
                <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                    {scanner.scanner_config.prompt || '(empty)'}
                </div>
            ),
        },
        {
            title: 'Sampling',
            key: 'sampling',
            render: (_, scanner) => (
                <span className="text-sm tabular-nums">
                    {(scanner.sampling_rate * 100).toFixed(scanner.sampling_rate < 0.1 ? 2 : 1)}%
                </span>
            ),
            sorter: (a, b) => a.sampling_rate - b.sampling_rate,
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
                description="Configure named scanners that PostHog applies to completed session recordings. Results land as queryable events."
                resourceType={{ type: 'replay_vision' }}
            />

            <VisionQuotaMeter />

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
                            onClick={() => push(urls.replayVision('new'))}
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
                        onChange={setSearch}
                        prefix={<IconSearch />}
                        className="max-w-sm"
                    />
                    <FilterPill<EnabledFilter>
                        label="Status"
                        options={ENABLED_OPTIONS}
                        value={enabledFilter}
                        onChange={setEnabledFilter}
                    />
                    <FilterPill<ScannerType>
                        label="Type"
                        options={TYPE_OPTIONS}
                        value={scannerTypeFilter}
                        onChange={setScannerTypeFilter}
                    />
                    {hasActiveFilters && (
                        <LemonButton type="tertiary" size="small" onClick={() => clearFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                    <div className="ml-auto">
                        <LemonButton type="secondary" onClick={() => loadScanners()} size="small">
                            Refresh
                        </LemonButton>
                    </div>
                </div>

                <LemonTable
                    columns={columns}
                    dataSource={filteredScanners}
                    loading={scannersLoading}
                    rowKey="id"
                    pagination={{ pageSize: 50 }}
                    nouns={['scanner', 'scanners']}
                    emptyState={
                        scanners.length === 0 ? (
                            <div className="flex flex-col items-center gap-3 p-8 text-center">
                                <IconEye className="text-3xl text-muted" />
                                <div className="text-muted">No scanners yet.</div>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => push(urls.replayVision('new'))}
                                >
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
