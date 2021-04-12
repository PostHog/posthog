import { BigQuery } from '@google-cloud/bigquery'
import * as contrib from '@posthog/plugin-contrib'
import * as AWS from 'aws-sdk'
import crypto from 'crypto'
import fetch from 'node-fetch'
import snowflake from 'snowflake-sdk'

export const imports = {
    crypto: crypto,
    'node-fetch': fetch,
    'snowflake-sdk': snowflake,
    '@google-cloud/bigquery': { BigQuery },
    '@posthog/plugin-contrib': contrib,
    'aws-sdk': AWS,
}
