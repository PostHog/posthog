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
import { replayLensesLogic } from './replayLensesLogic'
import { ENABLED_OPTIONS, EnabledFilter, LENS_TYPE_OPTIONS, LensType, ReplayLens } from './types'

const TYPE_OPTIONS: { value: LensType; label: string }[] = LENS_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
}))

export const scene: SceneExport = {
    component: ReplayLensesScene,
    logic: replayLensesLogic,
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

export function ReplayLensesScene(): JSX.Element {
    const { filteredLenses, lenses, lensesLoading, search, enabledFilter, lensTypeFilter, hasActiveFilters } =
        useValues(replayLensesLogic)
    const {
        loadLenses,
        deleteLens,
        duplicateLens,
        toggleLensEnabled,
        setSearch,
        setEnabledFilter,
        setLensTypeFilter,
        clearFilters,
    } = useActions(replayLensesLogic)
    const { push } = useActions(router)

    const columns: LemonTableColumns<ReplayLens> = [
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name),
            render: (_, lens) => (
                <div className="flex flex-col">
                    <Link to={urls.replayVision(lens.id)} className="font-semibold text-primary">
                        {lens.name || '(untitled)'}
                    </Link>
                    {lens.description && <div className="text-muted text-sm">{lens.description}</div>}
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, lens) => (
                <div className="flex items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch checked={lens.enabled} onChange={() => toggleLensEnabled(lens.id)} size="small" />
                    </AccessControlAction>
                    <span className={lens.enabled ? 'text-success' : 'text-muted'}>
                        {lens.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Type',
            key: 'lens_type',
            render: (_, lens) => <LemonTag type="option">{lens.lens_type}</LemonTag>,
            sorter: (a, b) => a.lens_type.localeCompare(b.lens_type),
        },
        {
            title: 'Config',
            key: 'config',
            render: (_, lens) => (
                <div className="max-w-md text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                    {lens.lens_config.prompt || '(empty)'}
                </div>
            ),
        },
        {
            title: 'Sampling',
            key: 'sampling',
            render: (_, lens) => (
                <span className="text-sm tabular-nums">
                    {(lens.sampling_rate * 100).toFixed(lens.sampling_rate < 0.1 ? 2 : 1)}%
                </span>
            ),
            sorter: (a, b) => a.sampling_rate - b.sampling_rate,
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, lens) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => push(urls.replayVision(lens.id))}
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
                            onClick={() => duplicateLens(lens.id)}
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
                                    title: `Delete "${lens.name || 'Untitled lens'}"?`,
                                    description: 'This cannot be undone.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => deleteLens(lens.id),
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
                description="Configure named lenses that PostHog applies to completed session recordings. Results land as queryable events."
                resourceType={{ type: 'replay_vision' }}
            />

            <VisionQuotaMeter />

            <SceneSection
                title="Lenses"
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => push(urls.replayVision('new'))}
                            data-attr="create-replay-lens"
                        >
                            New lens
                        </LemonButton>
                    </AccessControlAction>
                }
            >
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search lenses..."
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
                    <FilterPill<LensType>
                        label="Type"
                        options={TYPE_OPTIONS}
                        value={lensTypeFilter}
                        onChange={setLensTypeFilter}
                    />
                    {hasActiveFilters && (
                        <LemonButton type="tertiary" size="small" onClick={() => clearFilters()}>
                            Clear filters
                        </LemonButton>
                    )}
                    <div className="ml-auto">
                        <LemonButton type="secondary" onClick={() => loadLenses()} size="small">
                            Refresh
                        </LemonButton>
                    </div>
                </div>

                <LemonTable
                    columns={columns}
                    dataSource={filteredLenses}
                    loading={lensesLoading}
                    rowKey="id"
                    pagination={{ pageSize: 50 }}
                    nouns={['lens', 'lenses']}
                    emptyState={
                        lenses.length === 0 ? (
                            <div className="flex flex-col items-center gap-3 p-8 text-center">
                                <IconEye className="text-3xl text-muted" />
                                <div className="text-muted">No lenses yet.</div>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => push(urls.replayVision('new'))}
                                >
                                    Create your first lens
                                </LemonButton>
                            </div>
                        ) : (
                            <span className="text-muted">No lenses match your filters.</span>
                        )
                    }
                />
            </SceneSection>
        </SceneContent>
    )
}

export default ReplayLensesScene
