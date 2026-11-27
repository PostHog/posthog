import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight, IconInfo, IconSearch } from '@posthog/icons'
import {
    Button,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import type { BrandKindEnumApi, BrandStatusEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { BRANDS_PAGE_SIZE, aiVisibilityBrandsLogic } from './aiVisibilityBrandsLogic'

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

    const emptyText =
        status === 'suggested'
            ? 'Nothing to review. The daily run adds the sites answers cite for the first time.'
            : 'No brands here yet.'

    const rows = brandsError ? [] : (brands?.results ?? [])
    const count = brands?.count ?? 0
    const first = count === 0 ? 0 : (page - 1) * BRANDS_PAGE_SIZE + 1
    const last = Math.min(page * BRANDS_PAGE_SIZE, count)

    return (
        <div className="flex flex-col gap-3" data-attr="ai-visibility-brands-setting">
            <div className="flex flex-wrap items-center gap-2">
                <ToggleGroup
                    variant="outline"
                    aria-label="Brand status"
                    value={[status]}
                    onValueChange={(next: string[]) => next[0] && setStatus(next[0] as BrandStatusEnumApi)}
                    data-attr="ai-visibility-brands-status"
                >
                    {STATUS_OPTIONS.map(({ value, label }) => (
                        <ToggleGroupItem key={value} value={value}>
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <InputGroup size="sm" className="w-72 max-w-full">
                    <InputGroupAddon align="inline-start">
                        <InputGroupText>
                            <IconSearch />
                        </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        aria-label="Search brands"
                        placeholder="Search by name or domain"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        data-attr="ai-visibility-brands-search"
                    />
                </InputGroup>
            </div>
            {brandsError ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadBrands, loading: brandsLoading }}
                >
                    Couldn't load the brands. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : null}
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead>Brand</TableHead>
                        <TableHead>What it is</TableHead>
                        <TableHead expand>
                            <span className="inline-flex items-center gap-1">
                                Other names
                                <Tooltip>
                                    <TooltipTrigger delay={0} render={<span aria-label="About other names" />}>
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{ALIASES_TOOLTIP}</TooltipContent>
                                </Tooltip>
                            </span>
                        </TableHead>
                        <TableHead aria-label="Actions" />
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {brandsLoading && rows.length === 0 ? (
                        [0, 1, 2].map((row) => (
                            <TableRow key={row}>
                                <TableCell colSpan={4}>
                                    <Skeleton className="h-5 w-full" />
                                </TableCell>
                            </TableRow>
                        ))
                    ) : rows.length === 0 ? (
                        <TableRow>
                            <TableEmpty colSpan={4}>{emptyText}</TableEmpty>
                        </TableRow>
                    ) : (
                        rows.map((brand) => {
                            const updating = updatingIds.includes(brand.id)
                            return (
                                <TableRow key={brand.id}>
                                    <TableCell>
                                        <div className="flex flex-col">
                                            <Text size="xs" render={<span className="font-semibold" />}>
                                                {brand.name}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span />}>
                                                {brand.domain}
                                            </Text>
                                        </div>
                                    </TableCell>
                                    <TableCell>
                                        <Select<BrandKindEnumApi>
                                            value={brand.kind}
                                            onValueChange={(kind) => kind && labelBrand(brand.id, kind)}
                                        >
                                            <SelectTrigger
                                                aria-label={`What ${brand.name} is`}
                                                disabledReason={updating ? 'Saving…' : undefined}
                                                data-attr="ai-visibility-brand-kind"
                                            >
                                                <SelectValue>
                                                    {(value: BrandKindEnumApi | null) =>
                                                        KIND_OPTIONS.find((option) => option.value === value)?.label
                                                    }
                                                </SelectValue>
                                            </SelectTrigger>
                                            <SelectContent>
                                                {KIND_OPTIONS.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </TableCell>
                                    <TableCell>
                                        <TagsCombobox
                                            value={brand.aliases}
                                            onChange={(aliases) => updateBrand(brand.id, { aliases })}
                                            options={[]}
                                            placeholder="Add a name"
                                            allowCustomValues
                                            customValueNoun="name"
                                            disabledReason={updating ? 'Saving…' : undefined}
                                            dataAttr="ai-visibility-brand-aliases"
                                        />
                                    </TableCell>
                                    <TableCell>
                                        {brand.status === 'ignored' ? (
                                            <Button
                                                onClick={() => updateBrand(brand.id, { status: 'suggested' })}
                                                loading={updating}
                                                data-attr="ai-visibility-brand-restore"
                                            >
                                                Restore
                                            </Button>
                                        ) : (
                                            <Button
                                                onClick={() => updateBrand(brand.id, { status: 'ignored' })}
                                                loading={updating}
                                                data-attr="ai-visibility-brand-ignore"
                                            >
                                                Ignore
                                            </Button>
                                        )}
                                    </TableCell>
                                </TableRow>
                            )
                        })
                    )}
                </TableBody>
            </Table>
            {count > BRANDS_PAGE_SIZE ? (
                <div className="flex items-center justify-end gap-2">
                    <Text size="xs" variant="muted" render={<span />}>
                        {first}-{last} of {count}
                    </Text>
                    <Button
                        size="icon"
                        aria-label="Previous page"
                        tooltip="Previous page"
                        onClick={() => setPage(page - 1)}
                        disabledReason={page <= 1 ? 'This is the first page' : undefined}
                    >
                        <IconChevronLeft />
                    </Button>
                    <Button
                        size="icon"
                        aria-label="Next page"
                        tooltip="Next page"
                        onClick={() => setPage(page + 1)}
                        disabledReason={last >= count ? 'This is the last page' : undefined}
                    >
                        <IconChevronRight />
                    </Button>
                </div>
            ) : null}
        </div>
    )
}
