import { useActions, useValues } from 'kea'

import { IconBrowser, IconHide, IconImage, IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { MemberSelect } from 'lib/components/MemberSelect'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, HeatmapScreenshotType } from '~/types'

import { heatmapCaptureSettingsLogic, isUrlCoveredByAllowlist } from '../../components/heatmapCaptureSettingsLogic'
import { HeatmapsPricingNotice } from '../../components/HeatmapsPricingNotice'
import { HeatmapsWarnings } from '../../components/HeatmapsWarnings'
import { heatmapsEmptyState } from '../../emptyState/heatmapsEmptyState'
import { HEATMAPS_PER_PAGE, heatmapsSceneLogic } from './heatmapsSceneLogic'

export const scene: SceneExport = {
    component: HeatmapsScene,
    logic: heatmapsSceneLogic,
    productKey: ProductKey.HEATMAPS,
    emptyState: heatmapsEmptyState,
}

export function HeatmapsScene(): JSX.Element {
    const { savedHeatmaps, savedHeatmapsLoading, filters, totalCount } = useValues(heatmapsSceneLogic)
    const { deleteHeatmap, setHeatmapsFilters } = useActions(heatmapsSceneLogic)
    const { currentTeamId } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { settings, urlAllowlist, captureMode } = useValues(
        heatmapCaptureSettingsLogic({ teamId: currentTeamId ?? 0 })
    )
    const showCaptureStatus = !!settings && captureMode === 'url_allowlist'
    const wontCaptureTooltip = settings?.enforcement_enabled
        ? 'Not in your capture URLs, so this page is not collecting new heatmap data.'
        : 'Not in your capture URLs. When capture limits take effect, this page stops collecting new heatmap data.'

    const columns: LemonTableColumns<HeatmapScreenshotType> = [
        {
            title: 'Heatmap',
            dataIndex: 'name',
            render: (_, row) => {
                const wontCapture = showCaptureStatus && !!row.url && !isUrlCoveredByAllowlist(row.url, urlAllowlist)
                return (
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                            <Link to={urls.heatmap(row.short_id)} className="font-semibold truncate" title={row.name}>
                                {row.name}
                            </Link>
                            {wontCapture && (
                                <Tooltip title={wontCaptureTooltip}>
                                    <IconHide className="text-muted shrink-0" />
                                </Tooltip>
                            )}
                        </div>
                        <span className="text-xs text-muted truncate ph-no-capture" title={row.url ?? undefined}>
                            {row.url}
                        </span>
                        {row.data_url && row.data_url !== row.url && (
                            <span className="text-xs text-muted truncate ph-no-capture" title={row.data_url}>
                                <span>Data: </span>
                                <span>{row.data_url}</span>
                            </span>
                        )}
                        <span className="text-xs text-muted flex flex-wrap gap-x-1">
                            {row.created_at && <TZLabel time={row.created_at} />}
                            {row.created_by && (
                                <span className="truncate ph-no-capture">{`by ${row.created_by.first_name || row.created_by.email}`}</span>
                            )}
                        </span>
                    </div>
                )
            },
        },
        {
            title: 'Background',
            dataIndex: 'type',
            width: 140,
            render: (_, row) => (
                <LemonTag icon={row.type === 'iframe' ? <IconBrowser /> : <IconImage />}>
                    {row.type === 'iframe' ? 'Live page' : 'Screenshot'}
                </LemonTag>
            ),
        },
        {
            width: 48,
            render: function Render(_, row) {
                return (
                    <More
                        overlay={
                            <>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Heatmap}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={row.user_access_level}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => deleteHeatmap(row.short_id)}
                                        fullWidth
                                        loading={savedHeatmapsLoading}
                                    >
                                        Delete
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Heatmaps].name}
                description={sceneConfigurations[Scene.Heatmaps].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Heatmaps].iconType || 'default',
                }}
                actions={
                    todayRailNav ? (
                        <>
                            <Button
                                variant="outline"
                                id="heatmaps-feedback-button"
                                data-attr="heatmaps-feedback-button"
                            >
                                Send feedback
                            </Button>
                            <Shortcut
                                name="NewHeatmap"
                                keybind={[keyBinds.new]}
                                intent="New heatmap"
                                interaction="click"
                                scope={Scene.Heatmaps}
                            >
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Heatmap}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <Button
                                        variant="primary"
                                        render={<LinkPrimitive to={urls.heatmap('new')} />}
                                        data-attr="heatmaps-new-heatmap-button"
                                        tooltip="New heatmap"
                                    >
                                        <IconPlus />
                                        New heatmap
                                    </Button>
                                </AccessControlAction>
                            </Shortcut>
                        </>
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                id="heatmaps-feedback-button"
                                data-attr="heatmaps-feedback-button"
                            >
                                Send feedback
                            </LemonButton>
                            <Shortcut
                                name="NewHeatmap"
                                keybind={[keyBinds.new]}
                                intent="New heatmap"
                                interaction="click"
                                scope={Scene.Heatmaps}
                            >
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Heatmap}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        type="primary"
                                        to={urls.heatmap('new')}
                                        data-attr="heatmaps-new-heatmap-button"
                                        size="small"
                                        icon={<IconPlusSmall />}
                                        tooltip="New heatmap"
                                    >
                                        New heatmap
                                    </LemonButton>
                                </AccessControlAction>
                            </Shortcut>
                        </>
                    )
                }
            />
            <HeatmapsWarnings />
            <HeatmapsPricingNotice />
            <div className="flex justify-between gap-2 items-center flex-wrap">
                <Shortcut
                    name="SearchHeatmaps"
                    keybind={[keyBinds.filter]}
                    intent="Search heatmaps"
                    interaction="click"
                    scope={Scene.Heatmaps}
                >
                    <LemonInput
                        type="search"
                        placeholder="Search for heatmaps"
                        onChange={(value) => setHeatmapsFilters({ ...filters, search: value || '' })}
                        value={filters.search || ''}
                    />
                </Shortcut>

                <div className="flex flex-wrap items-center gap-2">
                    <span>Created by:</span>
                    <MemberSelect
                        value={filters.createdBy === 'All users' ? null : (filters.createdBy as string | number | null)}
                        onChange={(user) => setHeatmapsFilters({ ...filters, createdBy: user?.id || 'All users' })}
                    />
                </div>
            </div>
            <div className="mb-4">
                <LemonTable
                    dataSource={savedHeatmaps}
                    loading={savedHeatmapsLoading}
                    columns={columns}
                    rowKey="id"
                    tableLayout="fixed"
                    emptyState={
                        filters.search
                            ? 'No heatmaps match your search.'
                            : 'Create a heatmap to explore how visitors interact with a page.'
                    }
                    pagination={{
                        controlled: true,
                        pageSize: HEATMAPS_PER_PAGE,
                        currentPage: filters.page,
                        entryCount: totalCount,
                        onBackward:
                            (filters.page || 1) > 1
                                ? () => setHeatmapsFilters({ ...filters, page: Math.max(1, (filters.page || 1) - 1) })
                                : undefined,
                        onForward:
                            (filters.page || 1) * HEATMAPS_PER_PAGE < (totalCount || 0)
                                ? () => setHeatmapsFilters({ ...filters, page: (filters.page || 1) + 1 })
                                : undefined,
                    }}
                    nouns={['heatmap', 'heatmaps']}
                />
            </div>
        </SceneContent>
    )
}
