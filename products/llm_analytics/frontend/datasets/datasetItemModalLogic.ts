import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import 'kea-router'

import '~/lib/api'
import { DatasetItem } from '~/types'

import type { datasetItemModalLogicType } from './datasetItemModalLogicType'
import { EMPTY_JSON, isStringJsonObject } from './utils'

export type TraceMetadata = Required<Pick<DatasetItem, 'ref_trace_id' | 'ref_span_id' | 'ref_trace_timestamp'>> | null

export interface DatasetItemModalLogicProps {
    datasetItem?: DatasetItem | null
    traceMetadata?: TraceMetadata
}

export enum DatasetTab {
    Items = 'items',
    Metadata = 'metadata',
}

interface DatasetItemFormValues {
    input: string | null
    output: string | null
    metadata: string | null
}

export const DATASET_ITEMS_PER_PAGE = 50

export const datasetItemModalLogic = kea<datasetItemModalLogicType>([
    path(['scenes', 'llm-analytics', 'datasetItemModalLogic']),

    props({ datasetItem: null } as DatasetItemModalLogicProps),

    key(({ datasetItem }) => `dataset-item-${datasetItem?.id || 'new'}`),

    forms(() => ({
        datasetItemForm: {
            defaults: { input: EMPTY_JSON, output: EMPTY_JSON, metadata: EMPTY_JSON } as DatasetItemFormValues,

            errors: ({ input, output, metadata }) => ({
                input: !isStringJsonObject(input) ? 'Input must contain a valid JSON object' : undefined,
                output: !isStringJsonObject(output) ? 'Output must contain a valid JSON object' : undefined,
                metadata: !isStringJsonObject(metadata) ? 'Metadata must contain a valid JSON object' : undefined,
            }),

            submit: async (formValues) => {},
        },
    })),
])
