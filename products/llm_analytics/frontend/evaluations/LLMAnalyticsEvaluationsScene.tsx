import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCopy, IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSwitch,
    LemonTab,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { providerKeyStateLabel, providerLabel } from '../settings/providerKeyStateUtils'
import { TrialUsageMeter } from '../settings/TrialUsageMeter'
import {
    EvaluationMetrics,
    PASS_RATE_SUCCESS_THRESHOLD,
    PASS_RATE_WARNING_THRESHOLD,
} from './components/EvaluationMetrics'
import { OfflineEvaluationsTab } from './components/OfflineEvaluationsTab'
import { EvaluationStats, evaluationMetricsLogic } from './evaluationMetricsLogic'
import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationConfig } from './types'

export const scene: SceneExport = {
    component: LLMAnalyticsEvaluationsScene,
    logic: llmEvaluationsLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

function getActiveTab(
    pathname: string,
    searchParams: Record<string, unknown>,
    showOfflineEvals: boolean
): 'online-evals' | 'offline-evals' {
    if (!showOfflineEvals) {
        return 'online-evals'
    }

    const normalizedPathname = removeProjectIdIfPresent(pathname)
    const offlineEvaluationsPath = urls.llmAnalyticsOfflineEvaluations()
    if (normalizedPathname === offlineEvaluationsPath || normalizedPathname.startsWith(`${offlineEvaluationsPath}/`)) {
        return 'offline-evals'
    }

    const tab = searchParams.tab
    return tab === 'offline-evals' || tab === 'offline' ? 'offline-evals' : 'online-evals'
}

function LLMAnalyticsEvaluationsContent({ tabId }: { tabId?: string }): JSX.Element {
    const evaluationsLogic = llmEvaluationsLogic({ tabId })
    const metricsLogic = evaluationMetricsLogic({ tabId })
    const {
        evaluations,
        filteredEvaluations,
        evaluationsLoading,
        evaluationsFilter,
        dateFilter,
        unhealthyProviderKeysUsedByEvaluations,
    } = useValues(evaluationsLogic)
    const { setEvaluationsFilter, toggleEvaluationEnabled, duplicateEvaluation, loadEvaluations, setDates } =
        useActions(evaluationsLogic)
    const { evaluationsWithMetrics } = useValues(metricsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const evaluationUrl = (id: string): string => combineUrl(urls.llmAnalyticsEvaluation(id), searchParams).url
    const settingsUrl = urls.settings('environment-llm-analytics', 'llm-analytics-byok')

    const filteredEvaluationsWithMetrics = evaluationsWithMetrics.filter((evaluation: EvaluationConfig) =>
        filteredEvaluations.some((filtered) => filtered.id === evaluation.id)
    )

    if (!evaluationsLoading && evaluations.length === 0) {
        return <EvaluationTemplatesEmptyState />
    }

    const columns: LemonTableColumns<EvaluationConfig> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, evaluation) => (
                <div className="flex flex-col">
                    <Link to={evaluationUrl(evaluation.id)} className="font-semibold text-primary">
                        {evaluation.name}
                    </Link>
                    {evaluation.description && <div className="text-muted text-sm">{evaluation.description}</div>}
                </div>
            ),
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, evaluation) => (
                <div className="flex items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch
                            checked={evaluation.enabled}
                            onChange={() => toggleEvaluationEnabled(evaluation.id)}
                            size="small"
                            data-attr="toggle-evaluation-enabled"
                        />
                    </AccessControlAction>
                    <span className={evaluation.enabled ? 'text-success' : 'text-muted'}>
                        {evaluation.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Prompt',
            key: 'prompt',
            render: (_, evaluation) => (
                <div className="max-w-md">
                    <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                        {evaluation.evaluation_config.prompt || '(No prompt)'}
                    </div>
                </div>
            ),
        },
        {
            title: 'Triggers',
            key: 'conditions',
            render: (_, evaluation) => (
                <div className="flex flex-wrap gap-1">
                    {evaluation.conditions.map((condition) => (
                        <LemonTag key={condition.id} type="option">
                            {parseFloat(condition.rollout_percentage.toFixed(2))}%
                            {condition.properties.length > 0 &&
                                ` when ${condition.properties.length} condition${condition.properties.length !== 1 ? 's' : ''}`}
                        </LemonTag>
                    ))}
                    {evaluation.conditions.length === 0 && <span className="text-muted text-sm">No triggers</span>}
                </div>
            ),
        },
        {
            title: 'Runs',
            key: 'recent_stats',
            render: (_, evaluation: EvaluationConfig & { stats?: EvaluationStats }) => {
                const stats = evaluation.stats
                if (!stats || stats.runs_count === 0) {
                    return <span className="text-muted text-sm">No runs</span>
                }

                const passRateColor =
                    stats.pass_rate >= PASS_RATE_SUCCESS_THRESHOLD
                        ? 'text-success'
                        : stats.pass_rate >= PASS_RATE_WARNING_THRESHOLD
                          ? 'text-warning'
                          : 'text-danger'

                return (
                    <div className="flex flex-col items-center">
                        <div className="text-sm">
                            {stats.runs_count} run{stats.runs_count !== 1 ? 's' : ''}
                        </div>
                        <div className={`font-semibold ${passRateColor}`}>
                            {parseFloat(stats.pass_rate.toFixed(2))}%
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, evaluation) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => push(evaluationUrl(evaluation.id))}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() => duplicateEvaluation(evaluation.id)}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => {
                                deleteWithUndo({
                                    endpoint: `environments/${currentTeamId}/evaluations`,
                                    object: evaluation,
                                    callback: () => loadEvaluations(),
                                })
                            }}
                        />
                    </AccessControlAction>
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <TrialUsageMeter showSettingsLink={false} />

            {unhealthyProviderKeysUsedByEvaluations.length > 0 && (
                <LemonBanner type="warning">
                    <div className="space-y-2">
                        <p>Some evaluations are using API keys that need attention.</p>
                        <ul className="list-disc pl-5 space-y-1">
                            {unhealthyProviderKeysUsedByEvaluations.map((providerKey) => (
                                <li key={providerKey.id}>
                                    <span className="font-semibold">{providerKey.name}</span> (
                                    {providerLabel(providerKey.provider)}) - {providerKeyStateLabel(providerKey.state)}:{' '}
                                    {providerKey.error_message || 'Unknown error'}
                                </li>
                            ))}
                        </ul>
                        <Link to={settingsUrl}>Go to settings to fix API keys.</Link>
                    </div>
                </LemonBanner>
            )}

            <LemonBanner type="info" dismissKey="evals-billing-notice">
                Each evaluation run counts as an LLM analytics event.
            </LemonBanner>

            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Online evals</h2>
                    <p className="text-muted">
                        Configure evaluation prompts and triggers to automatically assess your LLM generations.
                    </p>
                </div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={combineUrl(urls.llmAnalyticsEvaluationTemplates(), searchParams).url}
                        data-attr="create-evaluation-button"
                        tooltip="Create evaluation"
                    >
                        Create evaluation
                    </LemonButton>
                </AccessControlAction>
            </div>

            <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />

            <EvaluationMetrics />

            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search online evals..."
                    value={evaluationsFilter}
                    data-attr="evaluations-search-input"
                    onChange={setEvaluationsFilter}
                    prefix={<IconSearch />}
                    className="max-w-sm"
                />
            </div>

            <LemonTable
                columns={columns}
                dataSource={filteredEvaluationsWithMetrics}
                loading={evaluationsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                nouns={['evaluation', 'evaluations']}
            />
        </div>
    )
}

export function LLMAnalyticsEvaluationsScene({ tabId }: { tabId?: string }): JSX.Element {
    const { searchParams, location } = useValues(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const evaluationsLogic = useMountedLogic(llmEvaluationsLogic({ tabId }))
    const metricsLogic = evaluationMetricsLogic({ tabId })
    const showOfflineEvals = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_OFFLINE_EVALS]
    const activeTab = getActiveTab(location.pathname, searchParams, showOfflineEvals)

    useAttachedLogic(metricsLogic, evaluationsLogic)

    const tabs: LemonTab<string>[] = [
        {
            key: 'online-evals',
            label: 'Online evals',
            content: <LLMAnalyticsEvaluationsContent tabId={tabId} />,
            link: combineUrl(urls.llmAnalyticsEvaluations(), {
                ...searchParams,
                tab: undefined,
                experiment: undefined,
            }).url,
            'data-attr': 'evaluations-tab',
        },
        ...(showOfflineEvals
            ? [
                  {
                      key: 'offline-evals',
                      label: (
                          <span className="inline-flex items-center gap-1">
                              <span>Offline evals</span>
                              <LemonTag type="completion" size="small">
                                  Alpha
                              </LemonTag>
                          </span>
                      ),
                      content: <OfflineEvaluationsTab tabId={tabId} />,
                      link: combineUrl(urls.llmAnalyticsOfflineEvaluations(), {
                          ...searchParams,
                          tab: undefined,
                          experiment: undefined,
                      }).url,
                      'data-attr': 'offline-evals-tab',
                  } as LemonTab<string>,
              ]
            : []),
        {
            key: 'settings',
            label: 'Settings',
            link: urls.settings('environment-llm-analytics', 'llm-analytics-byok'),
            content: <></>,
            'data-attr': 'settings-tab',
        },
    ]

    return (
        <BindLogic logic={llmEvaluationsLogic} props={{ tabId }}>
            <BindLogic logic={evaluationMetricsLogic} props={{ tabId }}>
                <SceneContent>
                    <SceneTitleSection
                        name="Evaluations"
                        description="Configure and monitor automated LLM output evaluations."
                        resourceType={{
                            type: 'llm_evaluations',
                        }}
                        actions={
                            <LemonButton
                                to="https://posthog.com/docs/llm-analytics/evaluations"
                                type="secondary"
                                targetBlank
                                size="small"
                            >
                                Documentation
                            </LemonButton>
                        }
                    />
                    <LemonTabs activeKey={activeTab} data-attr="evaluations-tabs" tabs={tabs} sceneInset />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}
