import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { IdentityMatchingLinkApi } from './generated/api.schemas'
import { identityMatchingLogic } from './identityMatchingLogic'

export const scene: SceneExport = {
    component: IdentityMatchingScene,
    logic: identityMatchingLogic,
}

const TIER_TAG_TYPE = {
    high: 'success',
    medium: 'warning',
    low: 'default',
} as const

function EvidenceCell({ link }: { link: IdentityMatchingLinkApi }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            <LemonTag>
                {link.shared_ip_days} IP-day{link.shared_ip_days === 1 ? '' : 's'}
            </LemonTag>
            {link.shared_ips > 1 && <LemonTag>{link.shared_ips} IPs</LemonTag>}
            {link.ua_exact_match && <LemonTag type="highlight">Same user agent</LemonTag>}
            {link.orphan_is_webview && <LemonTag type="highlight">Webview</LemonTag>}
            {link.device_type_complement && <LemonTag>Mobile + desktop</LemonTag>}
            {link.geo_city_match && <LemonTag>Same city</LemonTag>}
            {link.avg_path_jaccard > 0 && <LemonTag>{Math.round(link.avg_path_jaccard * 100)}% path overlap</LemonTag>}
            {link.orphan_paid_touch && !link.anchor_paid_touch && <LemonTag type="completion">New paid touch</LemonTag>}
        </div>
    )
}

export function IdentityMatchingScene(): JSX.Element {
    const { user } = useValues(userLogic)
    const { filters, links, linksCount, linksResponseLoading, runs, modelVersions } = useValues(identityMatchingLogic)
    const { setFilters } = useActions(identityMatchingLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="Identity matching is limited to staff users while in development." />
    }

    const columns: LemonTableColumns<IdentityMatchingLinkApi> = [
        {
            title: 'Anonymous visitor',
            dataIndex: 'orphan_distinct_id',
            render: (_, link) => (
                <Link to={urls.personByDistinctId(link.orphan_distinct_id)} className="font-mono">
                    {link.orphan_distinct_id}
                </Link>
            ),
        },
        {
            title: 'Matched person',
            dataIndex: 'anchor_person_key',
            render: (_, link) => (
                <Link to={urls.personByDistinctId(link.anchor_person_key)}>{link.anchor_person_key}</Link>
            ),
        },
        {
            title: 'Model',
            dataIndex: 'model_version',
            render: (_, link) => <LemonTag>{link.model_version}</LemonTag>,
        },
        {
            title: 'Score',
            dataIndex: 'score',
            sorter: (a, b) => a.score - b.score,
            render: (_, link) => link.score.toFixed(2),
        },
        {
            title: 'Margin',
            dataIndex: 'margin',
            render: (_, link) => link.margin.toFixed(2),
        },
        {
            title: 'Tier',
            dataIndex: 'tier',
            render: (_, link) => <LemonTag type={TIER_TAG_TYPE[link.tier]}>{link.tier}</LemonTag>,
        },
        {
            title: 'Evidence',
            render: (_, link) => <EvidenceCell link={link} />,
        },
        {
            title: 'Computed',
            dataIndex: 'computed_at',
            render: (_, link) => dayjs(link.computed_at).format('MMM D, YYYY HH:mm'),
        },
    ]

    return (
        <div className="space-y-4">
            <p className="text-secondary">
                Probable links between anonymous visitors and identified persons, recovered from first-party signals
                like shared IPs, device traits, and browsing overlap. Links are analytics-only suggestions — nothing is
                merged.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    placeholder="Latest run"
                    value={filters.jobId}
                    onChange={(jobId) => setFilters({ jobId })}
                    options={[
                        { value: null, label: 'Latest run' },
                        ...runs.map((run) => ({
                            value: run.job_id,
                            label: `${dayjs(run.computed_at).format('MMM D, HH:mm')} (${run.models
                                .map((model) => `${model.model_version}: ${model.link_count}`)
                                .join(', ')})`,
                        })),
                    ]}
                    size="small"
                />
                <LemonSelect
                    placeholder="All models"
                    value={filters.modelVersion}
                    onChange={(modelVersion) => setFilters({ modelVersion })}
                    options={[
                        { value: null, label: 'All models' },
                        ...modelVersions.map((version) => ({ value: version, label: version })),
                    ]}
                    size="small"
                />
                <LemonSelect
                    placeholder="All tiers"
                    value={filters.tier}
                    onChange={(tier) => setFilters({ tier })}
                    options={[
                        { value: null, label: 'All tiers' },
                        { value: 'high' as const, label: 'High' },
                        { value: 'medium' as const, label: 'Medium' },
                        { value: 'low' as const, label: 'Low' },
                    ]}
                    size="small"
                />
                <LemonInput
                    type="search"
                    placeholder="Search distinct IDs"
                    value={filters.search}
                    onChange={(search) => setFilters({ search })}
                    size="small"
                />
                <div className="ml-auto text-secondary">
                    {links.length < linksCount
                        ? `Showing ${links.length} of ${linksCount} links`
                        : `${linksCount} link${linksCount === 1 ? '' : 's'}`}
                </div>
            </div>
            {!linksResponseLoading && links.length === 0 ? (
                <LemonBanner type="info">
                    No identity matching links yet. Links appear after the identity matching job has run for this
                    project.
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={links}
                    columns={columns}
                    loading={linksResponseLoading}
                    rowKey={(link) => `${link.model_version}:${link.orphan_distinct_id}`}
                    pagination={{ pageSize: 50 }}
                />
            )}
        </div>
    )
}
