import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDownload, IconInfo, IconPerson } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonTab,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    LemonTag,
    Tooltip,
    Link,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { AccessDenied } from 'lib/components/AccessDenied'
import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import type { IdentityMatchingLinkApi } from './generated/api.schemas'
import { IdentityMatchingDetail } from './IdentityMatchingDetail'
import { LINKS_PAGE_SIZE, identityMatchingLogic } from './identityMatchingLogic'
import {
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    type SignalCategory,
    computeTierStats,
    extractSignals,
    linkPersonDisplay,
    normalizedScore,
} from './identityMatchingUtils'
import { PaidAttributionTimeline } from './PaidAttributionTimeline'
import { RunsHistory } from './RunsHistory'

export const scene: SceneExport = {
    component: IdentityMatchingScene,
    logic: identityMatchingLogic,
}

type ModelPreference = 'all' | 'logreg_v1' | 'rules_v1'

const TIER_TAG_TYPE: Record<string, 'success' | 'warning' | 'default'> = {
    high: 'success',
    medium: 'warning',
    low: 'default',
}

const CATEGORY_TAG_TYPE: Record<SignalCategory, 'default' | 'highlight' | 'completion'> = {
    network: 'highlight',
    device: 'highlight',
    behavior: 'default',
    attribution: 'completion',
}

function buildLinksCsv(links: IdentityMatchingLinkApi[]): string {
    const headers = [
        'orphan_distinct_id',
        'anchor_person_key',
        'model_version',
        'score',
        'margin',
        'tier',
        'shared_ip_days',
        'shared_ips',
        'min_ip_block_size',
        'geo_city_match',
        'timezone_match',
        'language_match',
        'ua_exact_match',
        'orphan_is_webview',
        'device_type_complement',
        'days_overlap',
        'avg_path_jaccard',
        'orphan_paid_touch',
        'anchor_paid_touch',
        'computed_at',
    ]
    const rows = links.map((l) =>
        [
            l.orphan_distinct_id,
            l.anchor_person_key,
            l.model_version,
            l.score,
            l.margin,
            l.tier,
            l.shared_ip_days,
            l.shared_ips,
            l.min_ip_block_size,
            l.geo_city_match,
            l.timezone_match,
            l.language_match,
            l.ua_exact_match,
            l.orphan_is_webview,
            l.device_type_complement,
            l.days_overlap,
            l.avg_path_jaccard,
            l.orphan_paid_touch,
            l.anchor_paid_touch,
            l.computed_at,
        ]
            .map((v) => {
                let s = String(v)
                if (/^\s*[=+\-@]/.test(s)) {
                    s = `'${s}`
                }
                return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s
            })
            .join(',')
    )
    return [headers.join(','), ...rows].join('\n')
}

function exportLinks(links: IdentityMatchingLinkApi[], totalCount: number): void {
    const csv = buildLinksCsv(links)
    const blob = new Blob([csv], { type: 'text/csv' })
    downloadBlob(blob, `identity_matching_links_${dayjs().format('YYYY-MM-DD')}.csv`)
    if (totalCount > links.length) {
        lemonToast.warning(
            `Exported ${links.length} of ${totalCount} links (current page only). Navigate to other pages to export remaining links.`
        )
    } else {
        lemonToast.success(`Exported ${links.length} links`)
    }
}

function createCohortFromLinks(links: IdentityMatchingLinkApi[], modelPreference: ModelPreference): void {
    const distinctIds = new Set<string>()
    for (const link of links) {
        if (modelPreference === 'all' || link.model_version === modelPreference) {
            distinctIds.add(link.orphan_distinct_id)
            distinctIds.add(link.anchor_person_key)
        }
    }
    const ids = Array.from(distinctIds)

    LemonDialog.openForm({
        title: 'Create cohort from identity matches',
        initialValues: { name: `Identity matches (${dayjs().format('YYYY-MM-DD')})` },
        content: (
            <LemonField name="name">
                <LemonInput placeholder="Cohort name" autoFocus />
            </LemonField>
        ),
        errors: { name: (name: string) => (!name ? 'You must enter a name' : undefined) },
        onSubmit: async ({ name }: Record<string, any>) => {
            try {
                const csvContent = ids
                    .map((id) =>
                        String(id)
                            .replace(/[\n\r]/g, ' ')
                            .replace(/[\s]*[=+\-@]/, "'$&")
                    )
                    .join('\n')
                const csvFile = new File([csvContent], 'distinct_ids.csv', { type: 'text/csv' })
                const formData = new FormData()
                formData.append('name', name)
                formData.append('description', `Created from identity matching links (${ids.length} distinct IDs)`)
                formData.append('is_static', 'true')
                formData.append('csv', csvFile)
                formData.append('filters', JSON.stringify({ properties: {} }))
                await api.cohorts.create(formData as unknown as Record<string, unknown>)
                lemonToast.success(`Created cohort "${name}" with ${ids.length} persons`)
            } catch {
                lemonToast.error('Failed to create cohort')
            }
        },
    })
}

function KpiBar({ links, loading }: { links: IdentityMatchingLinkApi[]; loading: boolean }): JSX.Element {
    const stats = computeTierStats(links)
    const highPct = stats.total > 0 ? Math.round((stats.high / stats.total) * 100) : 0
    const paidPct = stats.total > 0 ? Math.round((stats.paidTouches / stats.total) * 100) : 0

    if (loading) {
        return <div className="text-sm text-muted">Loading…</div>
    }

    return (
        <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-primary">{stats.total.toLocaleString()}</span>
            <span className="text-tertiary">links</span>
            <span className="text-border">·</span>
            <LemonTag type="success">{stats.high.toLocaleString()} high</LemonTag>
            <span className="text-tertiary">{highPct}%</span>
            <span className="text-border">·</span>
            <LemonTag type="warning">{stats.medium.toLocaleString()} medium</LemonTag>
            <span className="text-border">·</span>
            <LemonTag>{stats.low.toLocaleString()} low</LemonTag>
            <span className="text-border">·</span>
            <LemonTag type="completion">{stats.paidTouches.toLocaleString()} paid touches</LemonTag>
            <span className="text-tertiary">{paidPct}%</span>
        </div>
    )
}

export function IdentityMatchingScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        filters,
        links,
        linksCount,
        linksResponseLoading,
        runs,
        modelVersions,
        runsResponseLoading,
        page,
        activeTab,
    } = useValues(identityMatchingLogic)
    const { setFilters, setPage, setActiveTab } = useActions(identityMatchingLogic)

    const [detailLink, setDetailLink] = useState<IdentityMatchingLinkApi | null>(null)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="Identity matching is limited to staff users while in development." />
    }

    const tierStats = computeTierStats(links)

    const columns: LemonTableColumns<IdentityMatchingLinkApi> = [
        {
            title: 'Anonymous visitor',
            dataIndex: 'orphan_distinct_id',
            render: (_, link) => (
                <Link to={urls.personByDistinctId(link.orphan_distinct_id)}>
                    <PersonDisplay
                        person={linkPersonDisplay(link.orphan_person, link.orphan_distinct_id)}
                        noPopover
                        withIcon="sm"
                    />
                </Link>
            ),
        },
        {
            title: 'Matched person',
            dataIndex: 'anchor_person_key',
            render: (_, link) => (
                <Link to={urls.personByDistinctId(link.anchor_person_key)}>
                    <PersonDisplay
                        person={linkPersonDisplay(link.anchor_person, link.anchor_person_key)}
                        noPopover
                        withIcon="sm"
                    />
                </Link>
            ),
        },
        {
            title: 'Model',
            dataIndex: 'model_version',
            render: (_, link) => <LemonTag>{link.model_version}</LemonTag>,
            width: 110,
        },
        {
            title: (
                <span className="flex items-center gap-1">
                    Confidence
                    <Tooltip title="Normalized confidence score combining the model's score, tier, and margin over the runner-up candidate.">
                        <IconInfo className="text-xs text-tertiary" />
                    </Tooltip>
                </span>
            ),
            key: 'confidence',
            sorter: (a, b) => a.score - b.score,
            render: (_, link) => {
                const confidence = normalizedScore(link)
                const pct = Math.round(confidence * 100)
                return (
                    <div className="flex flex-col gap-1 min-w-28">
                        <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 rounded-full bg-bg-light overflow-hidden">
                                <div
                                    className={`h-full rounded-full ${
                                        pct >= 70 ? 'bg-success' : pct >= 40 ? 'bg-warning' : 'bg-muted'
                                    }`}
                                    style={{ width: `${pct}%` }}
                                />
                            </div>
                            <Tooltip title={`Raw score: ${link.score.toFixed(2)} (${link.model_version})`}>
                                <span className="text-xs font-mono text-secondary tabular-nums">{pct}%</span>
                            </Tooltip>
                        </div>
                        <div className="flex items-center gap-1.5">
                            <LemonTag type={TIER_TAG_TYPE[link.tier]}>{link.tier}</LemonTag>
                            <Tooltip title="Confidence gap over the runner-up candidate">
                                <span className="text-xs text-tertiary">gap {link.margin.toFixed(2)}</span>
                            </Tooltip>
                        </div>
                    </div>
                )
            },
            width: 180,
        },
        {
            title: 'Evidence',
            key: 'evidence',
            render: (_, link) => {
                const signals = extractSignals(link)
                return (
                    <div className="flex flex-col gap-1">
                        {CATEGORY_ORDER.map((cat) => {
                            const catSignals = signals.filter((s) => s.category === cat)
                            if (catSignals.length === 0) {
                                return null
                            }
                            return (
                                <div key={cat} className="flex items-center gap-1">
                                    <Tooltip title={CATEGORY_LABELS[cat]}>
                                        <span className="text-xs text-tertiary w-16 shrink-0">
                                            {CATEGORY_LABELS[cat]}
                                        </span>
                                    </Tooltip>
                                    <div className="flex flex-wrap gap-1">
                                        {catSignals.map((signal, i) => (
                                            <LemonTag key={`${cat}-${i}`} type={CATEGORY_TAG_TYPE[cat]}>
                                                {signal.label}
                                            </LemonTag>
                                        ))}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )
            },
        },
        {
            title: 'Computed',
            dataIndex: 'computed_at',
            render: (_, link) => dayjs(link.computed_at).format('MMM D, YYYY HH:mm'),
            width: 140,
        },
    ]

    const tabs: LemonTab<string>[] = [
        {
            key: 'links',
            label: (
                <span className="flex items-center gap-1.5">
                    Links
                    {linksCount > 0 && <LemonTag className="ml-1">{linksCount.toLocaleString()}</LemonTag>}
                </span>
            ),
            content: (
                <div className="space-y-4">
                    <KpiBar links={links} loading={linksResponseLoading} />
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSelect
                            placeholder="Latest run"
                            value={filters.jobId}
                            onChange={(jobId) => setFilters({ jobId })}
                            options={[
                                { value: null, label: 'Latest run' },
                                ...runs.map((run) => ({
                                    value: run.job_id,
                                    label: `${dayjs(run.computed_at).format('MMM D, HH:mm')} · ${run.total_links} links`,
                                })),
                            ]}
                            size="small"
                        />
                        <LemonSegmentedButton
                            value={filters.modelVersion ?? 'all'}
                            onChange={(modelVersion) =>
                                setFilters({ modelVersion: modelVersion === 'all' ? null : modelVersion })
                            }
                            options={[
                                { value: 'all' as const, label: 'All models' },
                                ...modelVersions.map((version) => ({ value: version, label: version })),
                            ]}
                            size="small"
                        />
                        <LemonInput
                            type="search"
                            placeholder="Search distinct IDs or emails"
                            value={filters.search}
                            onChange={(search) => setFilters({ search })}
                            size="small"
                        />
                        <div className="flex gap-2 ml-auto">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconDownload />}
                                disabled={links.length === 0}
                                onClick={() => exportLinks(links, linksCount)}
                            >
                                Export CSV
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconPerson />}
                                disabled={links.length === 0}
                                onClick={() =>
                                    createCohortFromLinks(links, (filters.modelVersion as ModelPreference) ?? 'all')
                                }
                            >
                                Create cohort
                            </LemonButton>
                        </div>
                    </div>
                    {!linksResponseLoading && links.length === 0 ? (
                        <LemonBanner
                            type="info"
                            action={{
                                to: 'https://posthog.com/docs',
                                targetBlank: true,
                                children: 'Learn more',
                            }}
                        >
                            No identity matching links yet. Links appear after the identity matching Dagster job has run
                            for this project. The job runs periodically — contact your growth team if you need to
                            trigger a run manually.
                        </LemonBanner>
                    ) : (
                        <LemonTable
                            dataSource={links}
                            columns={columns}
                            loading={linksResponseLoading}
                            rowKey={(link) => `${link.model_version}:${link.orphan_distinct_id}`}
                            pagination={{
                                controlled: true,
                                pageSize: LINKS_PAGE_SIZE,
                                currentPage: page,
                                entryCount: linksCount,
                                onBackward: page > 1 ? () => setPage(page - 1) : undefined,
                                onForward: page * LINKS_PAGE_SIZE < linksCount ? () => setPage(page + 1) : undefined,
                            }}
                            nouns={['link', 'links']}
                            onRow={(link) => ({
                                onClick: () => setDetailLink(link),
                                className: 'cursor-pointer',
                            })}
                        />
                    )}
                </div>
            ),
        },
        {
            key: 'paid_attribution',
            label: (
                <span className="flex items-center gap-1.5">
                    Paid attribution
                    {tierStats.paidTouches > 0 && (
                        <LemonTag type="completion" className="ml-1">
                            {tierStats.paidTouches}
                        </LemonTag>
                    )}
                </span>
            ),
            content: <PaidAttributionTimeline links={links} />,
        },
        {
            key: 'runs',
            label: 'Run history',
            content: (
                <RunsHistory
                    runs={runs}
                    selectedJobId={filters.jobId}
                    onSelect={(jobId) => setFilters({ jobId })}
                    loading={runsResponseLoading}
                />
            ),
        },
    ]

    return (
        <SceneContent className="pt-4">
            <div>
                <h1 className="text-xl font-bold">Identity matching</h1>
                <p className="text-sm text-secondary mt-1">
                    Probable links between anonymous visitors and identified persons, recovered from first-party
                    signals. Links are analytics-only suggestions — nothing is merged.
                </p>
            </div>
            <LemonTabs
                activeKey={activeTab}
                onChange={(key: string) => setActiveTab(key as typeof activeTab)}
                tabs={tabs}
                sceneInset
            />
            <LemonModal
                isOpen={detailLink !== null}
                onClose={() => setDetailLink(null)}
                width="56rem"
                title={
                    <div className="flex items-center gap-2">
                        <IconPerson className="text-lg" />
                        <span>Identity match detail</span>
                    </div>
                }
            >
                {detailLink && <IdentityMatchingDetail link={detailLink} />}
            </LemonModal>
        </SceneContent>
    )
}
