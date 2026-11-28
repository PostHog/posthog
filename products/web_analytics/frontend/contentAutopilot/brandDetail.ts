import { dayjs } from 'lib/dayjs'

import type { AEOBrandApi, AEOBrandDetailApi } from 'products/web_analytics/frontend/generated/api.schemas'
import { BrandKindEnumApi, BrandStatusEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { type KpiDelta, positionDelta, positionLabel } from './promptReport'
import { formatShare, shareChange } from './shares'

export type BrandDetailKpiKey = 'visibility' | 'citation_rate' | 'average_position' | 'positive_share'

/** One headline figure of a brand: the range's value, the range before, and the range's last day. */
export interface BrandDetailKpi {
    key: BrandDetailKpiKey
    label: string
    description: string
    /** Null when the range has no base for it, such as no cited answer for the position. */
    value: number | null
    emptyMessage: string
    formatted: string | null
    /** "vs. 40% prior", or null when the range before can't be compared. */
    subtitle: string | null
    /** Percentage points for a share and places for the position, as the two values are shown. */
    change: number | null
    changeLabel: string | null
    /** A lower position is better. */
    goodDirection: 'up' | 'down'
    /** The change as the AI visibility KPI tiles show it, or null when the range before can't be compared. */
    delta: KpiDelta | null
    /** The value on the last day with answers, such as "Nov 26: 42%", or null without one. */
    latest: string | null
}

const KPIS: {
    key: BrandDetailKpiKey
    label: string
    description: string
    emptyMessage: string
}[] = [
    {
        key: 'visibility',
        label: 'Visibility',
        description: 'Share of answers that name the brand or link to its site.',
        emptyMessage: 'No answers',
    },
    {
        key: 'citation_rate',
        label: 'Citation rate',
        description: 'Share of answers that link to a page on the brand’s site.',
        emptyMessage: 'No answers',
    },
    {
        key: 'average_position',
        label: 'Citation position',
        description:
            'Where the brand’s link sits among the sources of the answers that cite it, on average. #1 is first. Lower is better.',
        emptyMessage: 'Not cited',
    },
    {
        key: 'positive_share',
        label: 'Positive sentiment',
        description: 'Share of the scored answers naming the brand that speak about it positively.',
        emptyMessage: 'Not scored yet',
    },
]

const format = (key: BrandDetailKpiKey, value: number): string =>
    key === 'average_position' ? positionLabel(value) : formatShare(value)

const roundPosition = (position: number): number => Math.round(position * 10) / 10

const changeBetween = (key: BrandDetailKpiKey, value: number | null, previous: number | null): number | null => {
    if (value === null || previous === null) {
        return null
    }
    return key === 'average_position'
        ? Math.round((roundPosition(value) - roundPosition(previous)) * 10) / 10
        : shareChange(value, previous)
}

const changeLabel = (key: BrandDetailKpiKey, change: number): string => {
    if (change === 0) {
        return 'No change'
    }
    const sign = change > 0 ? '+' : ''
    return key === 'average_position' ? `${sign}${change}` : `${sign}${change} pts`
}

/** The four headline figures of a brand, each against the range before and with its last day for a tooltip. */
export const brandDetailKpis = (detail: AEOBrandDetailApi): BrandDetailKpi[] =>
    KPIS.map(({ key, label, description, emptyMessage }) => {
        const value = detail.current[key]
        const previous = detail.previous ? detail.previous[key] : null
        const latest = detail.latest ? detail.latest[key] : null
        const change = changeBetween(key, value, previous)
        const tooltip = `Against the ${detail.days} days before`
        return {
            key,
            label,
            description,
            value,
            emptyMessage,
            formatted: value === null ? null : format(key, value),
            subtitle: value !== null && previous !== null ? `vs. ${format(key, previous)} prior` : null,
            change,
            changeLabel: change === null ? null : changeLabel(key, change),
            goodDirection: key === 'average_position' ? 'down' : 'up',
            delta:
                change === null
                    ? null
                    : key === 'average_position'
                      ? positionDelta(change, `${tooltip}. Lower is better`)
                      : {
                            label: changeLabel(key, change),
                            direction: change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
                            tooltip: `${tooltip}, in percentage points`,
                        },
            latest:
                detail.latest_date && latest !== null
                    ? `${dayjs(detail.latest_date).format('MMM D')}: ${format(key, latest)}`
                    : null,
        }
    })

export interface BrandPickerOption {
    id: string
    name: string
    domain: string
}

export interface BrandPickerGroup {
    label: string
    options: BrandPickerOption[]
}

const GROUPS: { kind: BrandKindEnumApi; label: string }[] = [
    { kind: BrandKindEnumApi.Own, label: 'Your brand' },
    { kind: BrandKindEnumApi.Competitor, label: 'Competitors' },
    { kind: BrandKindEnumApi.Publisher, label: 'Publishers' },
]

/** The brands a person can switch to, by kind. Every own brand opens the same page, so the first one stands for
 *  them all. The open brand is always offered, so the picker can show it even when it is ignored or unlabeled. */
export const brandPickerGroups = (brands: AEOBrandApi[], current: AEOBrandApi | null): BrandPickerGroup[] => {
    const offered = brands.filter((brand) => brand.status !== BrandStatusEnumApi.Ignored || brand.id === current?.id)
    if (current && !offered.some((brand) => brand.id === current.id)) {
        offered.push(current)
    }
    const byName = (a: AEOBrandApi, b: AEOBrandApi): number => a.name.localeCompare(b.name)
    const groups: BrandPickerGroup[] = GROUPS.map(({ kind, label }) => {
        const ofKind = offered.filter((brand) => brand.kind === kind).sort(byName)
        const shown =
            kind === BrandKindEnumApi.Own
                ? [ofKind.find((brand) => brand.id === current?.id) ?? ofKind[0]].filter(
                      (brand): brand is AEOBrandApi => brand !== undefined
                  )
                : ofKind
        return { label, options: shown.map(({ id, name, domain }) => ({ id, name, domain })) }
    })
    const others = offered.filter((brand) => !GROUPS.some(({ kind }) => kind === brand.kind))
    if (others.length) {
        groups.push({
            label: 'Other',
            options: others.sort(byName).map(({ id, name, domain }) => ({ id, name, domain })),
        })
    }
    return groups.filter((group) => group.options.length > 0)
}

export type BrandKindLabel = { label: string; type: 'success' | 'warning' | 'muted' }

/** The tag beside a brand's name: whose brand it is to the project. */
export const brandKindTag = (kind: BrandKindEnumApi): BrandKindLabel | null =>
    kind === BrandKindEnumApi.Own
        ? { label: 'Your brand', type: 'success' }
        : kind === BrandKindEnumApi.Competitor
          ? { label: 'Competitor', type: 'warning' }
          : kind === BrandKindEnumApi.Publisher
            ? { label: 'Publisher', type: 'muted' }
            : null
