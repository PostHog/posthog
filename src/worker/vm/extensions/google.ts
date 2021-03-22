import * as BigQuery from '@google-cloud/bigquery'

type DummyCloud = {
    bigquery: typeof BigQuery
}

type DummyGoogle = {
    cloud: DummyCloud
}

export function createGoogle(): DummyGoogle {
    return {
        cloud: {
            bigquery: BigQuery,
        },
    }
}
