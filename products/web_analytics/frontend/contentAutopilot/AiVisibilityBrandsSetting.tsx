import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
} from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type {
    AEOBrandApi,
    BrandKindEnumApi,
    BrandStatusEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { BRANDS_PAGE_SIZE, aiVisibilityBrandsLogic } from './aiVisibilityBrandsLogic'
import { QuillAiVisibilityBrandsSetting } from './QuillAiVisibilityBrandsSetting'

const KIND_OPTIONS: { value: BrandKindEnumApi; label: string }[] = [
    { value: 'own', label: 'Your brand' },
    { value: 'competitor', label: 'Competitor' },
    { value: 'publisher', label: 'Publisher' },
    { value: 'unknown', label: 'Not labeled' },
]
const STATUS_OPTIONS: { value: BrandStatusEnumApi; label: string }[] = [
    { value: 'suggested', label: 'To review' },
    { value: 'confirmed', label: 'Confirmed' },
    { value: 'ignored', label: 'Ignored' },
]
const ALIASES_TOOLTIP = 'Names an answer can use for this brand. Rankings count an answer that uses any of them.'

/** Reviews the brand catalog the daily runs fill from cited sites. Confirmed competitors drive the Rankings tab. */
export const AiVisibilityBrandsSetting = (): JSX.Element => {
    const { brands, brandsLoading, brandsError, status, search, page, updatingIds } = useValues(aiVisibilityBrandsLogic)
    const { setStatus, setSearch, setPage, labelBrand, updateBrand, loadBrands } = useActions(aiVisibilityBrandsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const emptyText =
        status === 'suggested'
            ? 'Nothing to review. The daily run adds the sites answers cite for the first time.'
            : 'No brands here yet.'

    if (todayRailNav) {
        return (
            <QuillAiVisibilityBrandsSetting
                statusOptions={STATUS_OPTIONS}
                kindOptions={KIND_OPTIONS}
                aliasesTooltip={ALIASES_TOOLTIP}
                emptyText={emptyText}
            />
        )
    }

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-brands-setting">
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    value={status}
                    onChange={setStatus}
                    size="small"
                    options={STATUS_OPTIONS}
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
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadBrands, loading: brandsLoading }}
                >
                    Couldn't load the brands. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
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
                emptyState={emptyText}
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
                        tooltip: ALIASES_TOOLTIP,
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
