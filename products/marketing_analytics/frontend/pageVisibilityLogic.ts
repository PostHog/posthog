import { MakeLogicType, actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { buildTeamScopedPersistenceConfig } from 'lib/logic/persistence'
import { isValidRelativeOrAbsoluteDate, getDefaultInterval } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import {
    DeviceType,
    INITIAL_DATE_FROM,
    INITIAL_DATE_TO,
    INITIAL_INTERVAL,
    INITIAL_WEB_ANALYTICS_FILTER,
    exactMatchOperatorFor,
} from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { DateFilterState } from 'scenes/web-analytics/webAnalyticsLogic'

import { CompareFilter, WebAnalyticsConversionGoal, WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'
import { AvailableFeature, PropertyFilterType, PropertyOperator } from '~/types'

export interface pageVisibilityLogicValues {
    authorizedDomains: string[] // webAnalyticsLogic
    hasAvailableFeature: (feature: AvailableFeature, currentUsage?: number | undefined) => boolean // userLogic
    compareFilter: CompareFilter
    conversionGoal: WebAnalyticsConversionGoal | null
    countryFilter: string | null
    dateFilter: DateFilterState
    deviceTypeFilter: DeviceType | null
    domainFilter: string | null
    isPathCleaningEnabled: boolean
    rawWebAnalyticsFilters: WebAnalyticsPropertyFilters
    referrerFilter: string | null
    selectedHost: string | null
    shouldFilterTestAccounts: boolean
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    _compareFilter: CompareFilter
    _isPathCleaningEnabled: boolean
}

export interface pageVisibilityLogicActions {
    setCompareFilter: (compareFilter: CompareFilter) => { compareFilter: CompareFilter }
    setConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => {
        conversionGoal: WebAnalyticsConversionGoal | null
    }
    setCountryFilter: (countryCode: string | null) => { countryCode: string | null }
    setDates: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setDeviceTypeFilter: (deviceType: DeviceType | null) => { deviceType: DeviceType | null }
    setDomainFilter: (domain: string | null) => { domain: string | null }
    setIsPathCleaningEnabled: (enabled: boolean) => { enabled: boolean }
    setReferrerFilter: (referrer: string | null) => { referrer: string | null }
    setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => { shouldFilterTestAccounts: boolean }
    setWebAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => { filters: WebAnalyticsPropertyFilters }
}

export interface pageVisibilityLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        compareFilter: (compareFilter: CompareFilter, dateFilter: DateFilterState) => CompareFilter
        isPathCleaningEnabled: (
            enabled: boolean,
            hasAvailableFeature: (feature: AvailableFeature, currentUsage?: number | undefined) => boolean
        ) => boolean
        selectedHost: (domainFilter: string | null, authorizedDomains: string[]) => string | null
        webAnalyticsFilters: (
            rawFilters: WebAnalyticsPropertyFilters,
            selectedHost: string | null,
            deviceTypeFilter: DeviceType | null,
            countryFilter: string | null,
            referrerFilter: string | null,
            isPathCleaningEnabled: boolean
        ) => WebAnalyticsPropertyFilters
    }
}

export type pageVisibilityLogicType = MakeLogicType<
    pageVisibilityLogicValues,
    pageVisibilityLogicActions,
    Record<string, never>,
    pageVisibilityLogicMeta
>

export const pageVisibilityLogic = kea<pageVisibilityLogicType>([
    path(['products', 'marketingAnalytics', 'pageVisibilityLogic']),
    connect(() => ({
        values: [webAnalyticsLogic, ['authorizedDomains'], userLogic, ['hasAvailableFeature']],
    })),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => ({ conversionGoal }),
        setIsPathCleaningEnabled: (enabled: boolean) => ({ enabled }),
        setDomainFilter: (domain: string | null) => ({ domain }),
        setDeviceTypeFilter: (deviceType: DeviceType | null) => ({ deviceType }),
        setCountryFilter: (countryCode: string | null) => ({ countryCode }),
        setReferrerFilter: (referrer: string | null) => ({ referrer }),
        setWebAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => ({ filters }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
    }),
    reducers(() => {
        const persistConfig = buildTeamScopedPersistenceConfig('marketing_page_visibility__')
        return {
            dateFilter: [
                {
                    dateFrom: INITIAL_DATE_FROM,
                    dateTo: INITIAL_DATE_TO,
                    interval: INITIAL_INTERVAL,
                    isIntervalManuallySet: false,
                } as DateFilterState,
                persistConfig,
                {
                    setDates: ({ isIntervalManuallySet, interval }, { dateFrom, dateTo }) => {
                        const validDateFrom =
                            dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom) ? INITIAL_DATE_FROM : dateFrom
                        const validDateTo = dateTo && !isValidRelativeOrAbsoluteDate(dateTo) ? INITIAL_DATE_TO : dateTo
                        return {
                            dateFrom: validDateFrom,
                            dateTo: validDateTo,
                            interval: isIntervalManuallySet ? interval : getDefaultInterval(validDateFrom, validDateTo),
                            isIntervalManuallySet,
                        }
                    },
                },
            ],
            _compareFilter: [
                { compare: true } as CompareFilter,
                persistConfig,
                { setCompareFilter: (_, { compareFilter }) => compareFilter },
            ],
            conversionGoal: [
                null as WebAnalyticsConversionGoal | null,
                persistConfig,
                { setConversionGoal: (_, { conversionGoal }) => conversionGoal },
            ],
            _isPathCleaningEnabled: [true, persistConfig, { setIsPathCleaningEnabled: (_, { enabled }) => enabled }],
            domainFilter: [null as string | null, persistConfig, { setDomainFilter: (_, { domain }) => domain }],
            deviceTypeFilter: [
                null as DeviceType | null,
                persistConfig,
                { setDeviceTypeFilter: (_, { deviceType }) => deviceType },
            ],
            countryFilter: [
                null as string | null,
                persistConfig,
                { setCountryFilter: (_, { countryCode }) => countryCode },
            ],
            referrerFilter: [
                null as string | null,
                persistConfig,
                { setReferrerFilter: (_, { referrer }) => referrer },
            ],
            rawWebAnalyticsFilters: [
                INITIAL_WEB_ANALYTICS_FILTER,
                persistConfig,
                { setWebAnalyticsFilters: (_, { filters }) => filters },
            ],
            shouldFilterTestAccounts: [
                false,
                persistConfig,
                { setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts },
            ],
        }
    }),
    selectors({
        compareFilter: [
            (s) => [s._compareFilter, s.dateFilter],
            (compareFilter: CompareFilter, dateFilter: DateFilterState): CompareFilter =>
                dateFilter.dateFrom === 'all' ? { compare: false } : compareFilter,
        ],
        isPathCleaningEnabled: [
            (s) => [s._isPathCleaningEnabled, s.hasAvailableFeature],
            (
                enabled: boolean,
                hasAvailableFeature: (feature: AvailableFeature, currentUsage?: number | undefined) => boolean
            ): boolean => hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && enabled,
        ],
        selectedHost: [
            (s) => [s.domainFilter, s.authorizedDomains],
            (domainFilter: string | null, authorizedDomains: string[]): string | null =>
                domainFilter && domainFilter !== 'all' && authorizedDomains.includes(domainFilter)
                    ? domainFilter.replace(/^https?:\/\//, '')
                    : null,
        ],
        webAnalyticsFilters: [
            (s) => [
                s.rawWebAnalyticsFilters,
                s.selectedHost,
                s.deviceTypeFilter,
                s.countryFilter,
                s.referrerFilter,
                s.isPathCleaningEnabled,
            ],
            (
                rawFilters: WebAnalyticsPropertyFilters,
                selectedHost: string | null,
                deviceTypeFilter: DeviceType | null,
                countryFilter: string | null,
                referrerFilter: string | null,
                isPathCleaningEnabled: boolean
            ): WebAnalyticsPropertyFilters => {
                const filters = rawFilters.map((filter) =>
                    filter.type === PropertyFilterType.Cohort || filter.operator !== PropertyOperator.Exact
                        ? filter
                        : {
                              ...filter,
                              operator: exactMatchOperatorFor(filter.key, filter.type, isPathCleaningEnabled),
                          }
                )
                if (selectedHost) {
                    filters.push({
                        key: '$host',
                        value: selectedHost,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                }
                if (deviceTypeFilter) {
                    filters.push({
                        key: '$device_type',
                        value: deviceTypeFilter === 'Desktop' ? 'Desktop' : ['Mobile', 'Tablet'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                }
                if (countryFilter) {
                    filters.push({
                        key: '$geoip_country_code',
                        value: countryFilter,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                }
                if (referrerFilter) {
                    filters.push({
                        key: '$referring_domain',
                        value: referrerFilter,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    })
                }
                return filters
            },
        ],
    }),
    actionToUrl(({ values, cache }) => {
        const buildUrl = (): [string, string] | undefined => {
            if (cache.applyingUrlState) {
                return undefined
            }
            const searchParams = new URLSearchParams()
            searchParams.set('tab', 'page-visibility')
            searchParams.set('date_from', values.dateFilter.dateFrom ?? '')
            searchParams.set('date_to', values.dateFilter.dateTo ?? '')
            searchParams.set('interval', values.dateFilter.interval)
            searchParams.set('compare_filter', JSON.stringify(values._compareFilter))
            searchParams.set('path_cleaning', values._isPathCleaningEnabled.toString())
            searchParams.set('filter_test_accounts', values.shouldFilterTestAccounts.toString())
            if (values.rawWebAnalyticsFilters.length) {
                searchParams.set('filters', JSON.stringify(values.rawWebAnalyticsFilters))
            }
            if (values.conversionGoal) {
                const [key, value] = Object.entries(values.conversionGoal)[0]
                searchParams.set(`conversionGoal.${key}`, String(value))
            }
            if (values.domainFilter) {
                searchParams.set('domain', values.domainFilter)
            }
            if (values.deviceTypeFilter) {
                searchParams.set('device_type', values.deviceTypeFilter)
            }
            if (values.countryFilter) {
                searchParams.set('country', values.countryFilter)
            }
            if (values.referrerFilter) {
                searchParams.set('referrer', values.referrerFilter)
            }
            return [urls.marketingAnalyticsApp(), searchParams.toString()]
        }
        return {
            setDates: buildUrl,
            setCompareFilter: buildUrl,
            setConversionGoal: buildUrl,
            setIsPathCleaningEnabled: buildUrl,
            setDomainFilter: buildUrl,
            setDeviceTypeFilter: buildUrl,
            setCountryFilter: buildUrl,
            setReferrerFilter: buildUrl,
            setWebAnalyticsFilters: buildUrl,
            setShouldFilterTestAccounts: buildUrl,
        }
    }),
    urlToAction(({ actions, cache }) => ({
        '/marketing': (_, searchParams) => {
            if (searchParams.tab !== 'page-visibility') {
                return
            }
            cache.applyingUrlState = true
            try {
                if (searchParams.date_from !== undefined || searchParams.date_to !== undefined) {
                    actions.setDates(searchParams.date_from || null, searchParams.date_to || null)
                }
                if (searchParams.compare_filter) {
                    actions.setCompareFilter(searchParams.compare_filter)
                }
                if (searchParams.filters) {
                    actions.setWebAnalyticsFilters(searchParams.filters)
                }
                if (searchParams['conversionGoal.actionId']) {
                    actions.setConversionGoal({ actionId: Number(searchParams['conversionGoal.actionId']) })
                } else if (searchParams['conversionGoal.customEventName']) {
                    actions.setConversionGoal({ customEventName: searchParams['conversionGoal.customEventName'] })
                }
                if (searchParams.path_cleaning !== undefined) {
                    actions.setIsPathCleaningEnabled(searchParams.path_cleaning === 'true')
                }
                if (searchParams.filter_test_accounts !== undefined) {
                    actions.setShouldFilterTestAccounts(searchParams.filter_test_accounts === 'true')
                }
                actions.setDomainFilter(searchParams.domain ?? null)
                actions.setDeviceTypeFilter(searchParams.device_type ?? null)
                actions.setCountryFilter(searchParams.country ?? null)
                actions.setReferrerFilter(searchParams.referrer ?? null)
            } finally {
                cache.applyingUrlState = false
            }
        },
    })),
])
