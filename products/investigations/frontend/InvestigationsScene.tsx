import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { InvestigationSummaryApi } from './generated/api.schemas'
import { investigationsEmptyState } from './investigationsEmptyState'
import { investigationsLogic } from './investigationsLogic'
import { NewInvestigationButton } from './NewInvestigationButton'

export const scene: SceneExport = {
    component: InvestigationsScene,
    logic: investigationsLogic,
    productKey: ProductKey.INVESTIGATIONS,
    emptyState: investigationsEmptyState,
}

export function InvestigationsScene(): JSX.Element {
    const { result, resultLoading, search, page, error } = useValues(investigationsLogic)
    const { setSearch, setPage, loadInvestigations } = useActions(investigationsLogic)
    return (
        <SceneContent>
            <SceneTitleSection
                name="Investigations"
                description="Investigate a question, test explanations, and share the evidence behind your decision."
                resourceType={{ type: 'investigation' }}
                actions={<NewInvestigationButton />}
            />
            {error ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadInvestigations() }}>
                    {error}
                </LemonBanner>
            ) : (
                <>
                    <LemonInput
                        type="search"
                        placeholder="Search investigations"
                        value={search}
                        onChange={setSearch}
                        className="max-w-100"
                    />
                    <LemonTable<InvestigationSummaryApi>
                        dataSource={result?.results ?? []}
                        loading={resultLoading || !result}
                        rowKey="id"
                        emptyState={
                            search
                                ? 'No investigations match your search.'
                                : 'Start with a question, or explore a worked example from New investigation.'
                        }
                        columns={[
                            {
                                title: 'Question',
                                key: 'question',
                                render: (_, item) => (
                                    <Link to={urls.investigation(item.id)}>
                                        {item.question || 'Untitled investigation'}
                                    </Link>
                                ),
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                render: (_, item) => (
                                    <LemonTag>
                                        {item.status === 'investigating'
                                            ? 'Investigating'
                                            : item.status === 'review'
                                              ? 'Ready for review'
                                              : item.status === 'monitoring'
                                                ? 'Monitoring'
                                                : 'Closed'}
                                    </LemonTag>
                                ),
                            },
                            { title: 'Evidence', dataIndex: 'evidence_count', width: 100 },
                            { title: 'Runs', dataIndex: 'run_count', width: 80 },
                            {
                                title: 'Updated',
                                key: 'updated',
                                render: (_, item) => <TZLabel time={item.updated_at} />,
                            },
                        ]}
                        pagination={{
                            currentPage: page,
                            pageSize: 30,
                            entryCount: result?.count ?? 0,
                            onForward: () => setPage(page + 1),
                            onBackward: () => setPage(page - 1),
                        }}
                    />
                </>
            )}
        </SceneContent>
    )
}
