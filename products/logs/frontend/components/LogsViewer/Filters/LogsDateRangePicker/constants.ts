import { DateMappingOption } from '~/types'

export const LOGS_DATE_OPTIONS: DateMappingOption[] = [
    { key: 'Last 1 minute', values: ['-1M'], defaultInterval: 'minute' },
    { key: 'Last 5 minutes', values: ['-5M'], defaultInterval: 'minute' },
    { key: 'Last 15 minutes', values: ['-15M'], defaultInterval: 'minute' },
    { key: 'Last 30 minutes', values: ['-30M'], defaultInterval: 'minute' },
    { key: 'Last 1 hour', values: ['-1h'], defaultInterval: 'hour' },
    { key: 'Last 3 hours', values: ['-3h'], defaultInterval: 'hour' },
    { key: 'Last 6 hours', values: ['-6h'], defaultInterval: 'hour' },
    { key: 'Last 12 hours', values: ['-12h'], defaultInterval: 'hour' },
    { key: 'Last 24 hours', values: ['-24h'], defaultInterval: 'hour' },
    { key: 'Last 3 days', values: ['-3d'], defaultInterval: 'day' },
    { key: 'Last 7 days', values: ['-7d'], defaultInterval: 'day' },
]
