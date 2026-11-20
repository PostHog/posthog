import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
} from '@posthog/lemon-ui'

import type { AEOBrandApi, BrandKindEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { BRANDS_PAGE_SIZE, aiVisibilityBrandsLogic } from './aiVisibilityBrandsLogic'

const KIND_OPTIONS: { value: BrandKindEnumApi; label: string }[] = [
    { value: 'own', label: 'Your brand' },
    { value: 'competitor', label: 'Competitor' },
    { value: 'publisher', label: 'Publisher' },
    { value: 'unknown', label: 'Not labeled' },
]

/** Reviews the brand catalog the daily runs fill from cited sites. Confirmed competitors drive the Rankings tab. */
export const AiVisibilityBrandsSetting = (): JSX.Element => {
    const { brands, brandsLoading, brandsError, status, search, page, updatingIds } = useValues(aiVisibilityBrandsLogic)
    const { setStatus, setSearch, setPage, labelBrand, updateBrand, loadBrands } = useActions(aiVisibilityBrandsLogic)

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-brands-setting">
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    value={status}
                    onChange={setStatus}
                    size="small"
                    options={[
                        { value: 'suggested', label: 'To review' },
                        { value: 'confirmed', label: 'Confirmed' },
                        { value: 'ignored', label: 'Ignored' },
                    ]}
                    data-attr="ai-visibility-brands-status"
                />
                <LemonInput
                    type="search"
                    size="small"
                    placeholder="Search by name or domain"
                    value={search}
                    onChange={setSearch}
                    className="w-72"
                    data-attr="ai-visibility-brands-search"
                />
            </div>
            {brandsError ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadBrands, loading: brandsLoading }}
                >
                    Couldn't load the brands. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : null}
            <LemonTable<AEOBrandApi>
                size="small"
                dataSource={brandsError ? [] : (brands?.results ?? [])}
                loading={brandsLoading}
                rowKey="id"
                pagination={{
                    controlled: true,
                    pageSize: BRANDS_PAGE_SIZE,
                    currentPage: page,
                    entryCount: brands?.count ?? 0,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
                emptyState={
                    status === 'suggested'
                        ? 'Nothing to review. The daily run adds the sites answers cite for the first time.'
                        : 'No brands here yet.'
                }
                columns={[
                    {
                        title: 'Brand',
                        key: 'name',
                        render: (_, brand) => (
                            <div className="flex flex-col">
                                <span className="font-semibold">{brand.name}</span>
                                <span className="text-xs text-muted">{brand.domain}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'What it is',
                        key: 'kind',
                        render: (_, brand) => (
                            <LemonSelect
                                size="small"
                                value={brand.kind}
                                options={KIND_OPTIONS}
                                onSelect={(kind) => kind && labelBrand(brand.id, kind)}
                                disabledReason={updatingIds.includes(brand.id) ? 'Saving…' : undefined}
                                data-attr="ai-visibility-brand-kind"
                            />
                        ),
                    },
                    {
                        title: 'Other names',
                        key: 'aliases',
                        tooltip:
                            'Names an answer can use for this brand. Rankings count an answer that uses any of them.',
                        render: (_, brand) => (
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                size="small"
                                value={brand.aliases}
                                onChange={(aliases) => updateBrand(brand.id, { aliases })}
                                placeholder="Add a name"
                                disabled={updatingIds.includes(brand.id)}
                                data-attr="ai-visibility-brand-aliases"
                            />
                        ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, brand) =>
                            brand.status === 'ignored' ? (
                                <LemonButton
                                    size="small"
                                    onClick={() => updateBrand(brand.id, { status: 'suggested' })}
                                    loading={updatingIds.includes(brand.id)}
                                    data-attr="ai-visibility-brand-restore"
                                >
                                    Restore
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    size="small"
                                    onClick={() => updateBrand(brand.id, { status: 'ignored' })}
                                    loading={updatingIds.includes(brand.id)}
                                    data-attr="ai-visibility-brand-ignore"
                                >
                                    Ignore
                                </LemonButton>
                            ),
                    },
                ]}
            />
        </div>
    )
}
