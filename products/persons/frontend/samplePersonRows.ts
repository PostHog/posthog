import type { Dayjs } from 'lib/dayjs'

import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    type SampleIds,
    type SampleRowsSource,
    buildSampleRows,
    samplePersonDisplayName,
    samplePropertyValue,
} from '~/queries/nodes/DataTable/sampleRows'

interface SamplePerson {
    email: string
    properties: Record<string, string>
    daysSinceCreated: number
    minutesSinceSeen: number
}

const SAMPLE_PERSONS: SamplePerson[] = [
    {
        email: 'alice@example.com',
        properties: { name: 'Alice', $geoip_country_code: 'US', $browser: 'Chrome', $os: 'Mac OS X' },
        daysSinceCreated: 2,
        minutesSinceSeen: 1,
    },
    {
        email: 'bob@example.com',
        properties: { name: 'Bob', $geoip_country_code: 'GB', $browser: 'Firefox', $os: 'Windows' },
        daysSinceCreated: 5,
        minutesSinceSeen: 3,
    },
    {
        email: 'carol@example.com',
        properties: { name: 'Carol', $geoip_country_code: 'DE', $browser: 'Mobile Safari', $os: 'iOS' },
        daysSinceCreated: 9,
        minutesSinceSeen: 6,
    },
    {
        email: 'dave@example.com',
        properties: { name: 'Dave', $geoip_country_code: 'FR', $browser: 'Chrome', $os: 'Linux' },
        daysSinceCreated: 14,
        minutesSinceSeen: 12,
    },
    {
        email: 'erin@example.com',
        properties: { name: 'Erin', $geoip_country_code: 'BR', $browser: 'Safari', $os: 'Mac OS X' },
        daysSinceCreated: 21,
        minutesSinceSeen: 95,
    },
    {
        email: 'frank@example.com',
        properties: { name: 'Frank', $geoip_country_code: 'JP', $browser: 'Chrome', $os: 'Android' },
        daysSinceCreated: 30,
        minutesSinceSeen: 240,
    },
]

function sampleValue(key: string, sample: SamplePerson, ids: SampleIds, now: Dayjs): unknown {
    const properties = { email: sample.email, ...sample.properties }

    if (key === 'person_display_name') {
        return samplePersonDisplayName(sample.email, ids)
    }
    if (key === 'person') {
        return { id: ids.personId, distinct_ids: [ids.distinctId], properties }
    }
    if (key === 'id') {
        return ids.personId
    }
    if (key === 'created_at') {
        return now.subtract(sample.daysSinceCreated, 'day').toISOString()
    }
    if (key === 'last_seen_at') {
        return now.subtract(sample.minutesSinceSeen, 'minute').toISOString()
    }
    return samplePropertyValue(key, properties)
}

export function buildSamplePersonRows(columns: string[], now: Dayjs): (DataTableRow & { result: unknown[] })[] {
    return buildSampleRows(SAMPLE_PERSONS, columns, (key, sample, ids) => sampleValue(key, sample, ids, now))
}

export const SAMPLE_PERSONS_SOURCE: SampleRowsSource = {
    buildRows: buildSamplePersonRows,
    // pinned: the data-attr value is an autocapture selector, so renaming it breaks dashboards
    dataAttr: 'persons-table-sample-data',
    hiddenColumns: ['person.$delete'],
}
