import { BigQuery } from '@google-cloud/bigquery'
import crypto from 'crypto'
import fetch from 'node-fetch'
import snowflake from 'snowflake-sdk'

export const imports = {
    crypto: crypto,
    'node-fetch': fetch,
    'snowflake-sdk': snowflake,
    '@google-cloud/bigquery': { BigQuery },
}
