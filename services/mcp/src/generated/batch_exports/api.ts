/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const BatchExportsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const BatchExportsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const BatchExportsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const batchExportsCreateBodyDestinationOneOneConfigUseVariantTypeDefault = true
export const batchExportsCreateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault = true
export const batchExportsCreateBodyDestinationOneTwoConfigPrefixDefault = ``
export const batchExportsCreateBodyDestinationOneTwoConfigFileFormatDefault = `JSONLines`
export const batchExportsCreateBodyDestinationOneThreeConfigTableIdDefault = `events`
export const batchExportsCreateBodyDestinationOneThreeConfigUseJsonTypeDefault = false
export const batchExportsCreateBodyOffsetDayMin = 0
export const batchExportsCreateBodyOffsetDayMax = 6

export const batchExportsCreateBodyOffsetHourMin = 0
export const batchExportsCreateBodyOffsetHourMax = 23

export const BatchExportsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().describe('Human-readable name for the batch export.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions')
            .optional()
            .describe(
                'Which data model to export (events, persons, sessions).\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .union([
                zod
                    .object({
                        type: zod.enum(['Databricks']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsCreateBodyDestinationOneOneConfigUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsCreateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a Databricks batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['AzureBlob']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsCreateBodyDestinationOneTwoConfigPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsCreateBodyDestinationOneTwoConfigFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating an Azure Blob Storage batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['BigQuery']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a google-cloud-service-account-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                dataset_id: zod.string().describe('BigQuery dataset ID to write to.'),
                                table_id: zod
                                    .string()
                                    .default(batchExportsCreateBodyDestinationOneThreeConfigTableIdDefault)
                                    .describe('BigQuery table ID inside the dataset.'),
                                use_json_type: zod
                                    .boolean()
                                    .default(batchExportsCreateBodyDestinationOneThreeConfigUseJsonTypeDefault)
                                    .describe(
                                        "Whether to export 'properties', 'set', and 'set_once' fields as the BigQuery JSON type rather than STRING. Cannot be changed after the export is created."
                                    ),
                            })
                            .describe(
                                'Typed configuration for a BigQuery batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors the\nnon-credential fields of `BigQueryBatchExportInputs` in\n`products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a BigQuery batch-export destination.'),
            ])
            .describe('Destination configuration. Required integration_id is enforced per destination type.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether the batch export is paused.'),
        timezone: zod
            .string()
            .nullish()
            .describe(
                "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries."
            ),
        offset_day: zod
            .number()
            .min(batchExportsCreateBodyOffsetDayMin)
            .max(batchExportsCreateBodyOffsetDayMax)
            .nullish()
            .describe('Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).'),
        offset_hour: zod
            .number()
            .min(batchExportsCreateBodyOffsetHourMin)
            .max(batchExportsCreateBodyOffsetHourMax)
            .nullish()
            .describe('Hour-of-day offset (0-23) for daily and weekly intervals.'),
    })
    .describe(
        'Request body for create/partial_update on BatchExportViewSet.\n\nMirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic\n`destination` schema so integration_id is marked required on the types that need\nit. Responses continue to use `BatchExportSerializer`.'
    )

export const BatchExportsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch export.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const BatchExportsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch export.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const batchExportsPartialUpdateBodyDestinationOneOneConfigUseVariantTypeDefault = true
export const batchExportsPartialUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault = true
export const batchExportsPartialUpdateBodyDestinationOneTwoConfigPrefixDefault = ``
export const batchExportsPartialUpdateBodyDestinationOneTwoConfigFileFormatDefault = `JSONLines`
export const batchExportsPartialUpdateBodyDestinationOneThreeConfigTableIdDefault = `events`
export const batchExportsPartialUpdateBodyDestinationOneThreeConfigUseJsonTypeDefault = false
export const batchExportsPartialUpdateBodyOffsetDayMin = 0
export const batchExportsPartialUpdateBodyOffsetDayMax = 6

export const batchExportsPartialUpdateBodyOffsetHourMin = 0
export const batchExportsPartialUpdateBodyOffsetHourMax = 23

export const BatchExportsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().optional().describe('Human-readable name for the batch export.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions')
            .optional()
            .describe(
                'Which data model to export (events, persons, sessions).\n\n* `events` - Events\n* `persons` - Persons\n* `sessions` - Sessions'
            ),
        destination: zod
            .union([
                zod
                    .object({
                        type: zod.enum(['Databricks']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                http_path: zod.string().describe('Databricks SQL warehouse HTTP path.'),
                                catalog: zod.string().describe('Unity Catalog name.'),
                                schema: zod.string().describe('Schema (database) name inside the catalog.'),
                                table_name: zod.string().describe('Destination table name.'),
                                use_variant_type: zod
                                    .boolean()
                                    .default(batchExportsPartialUpdateBodyDestinationOneOneConfigUseVariantTypeDefault)
                                    .describe('Whether to use the Databricks VARIANT type for JSON-like columns.'),
                                use_automatic_schema_evolution: zod
                                    .boolean()
                                    .default(
                                        batchExportsPartialUpdateBodyDestinationOneOneConfigUseAutomaticSchemaEvolutionDefault
                                    )
                                    .describe(
                                        'Whether to let Databricks evolve the destination table schema automatically.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for a Databricks batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a Databricks batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['AzureBlob']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                container_name: zod.string().describe('Azure Blob Storage container name.'),
                                prefix: zod
                                    .string()
                                    .default(batchExportsPartialUpdateBodyDestinationOneTwoConfigPrefixDefault)
                                    .describe('Object key prefix applied to every exported file.'),
                                compression: zod
                                    .union([
                                        zod
                                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                            .describe(
                                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                            ),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe(
                                        'Optional compression codec applied to exported files. Valid codecs depend on file_format.\n\n* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                    ),
                                file_format: zod
                                    .enum(['JSONLines', 'Parquet'])
                                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                                    .default(batchExportsPartialUpdateBodyDestinationOneTwoConfigFileFormatDefault)
                                    .describe(
                                        'File format used for exported objects.\n\n* `JSONLines` - JSONLines\n* `Parquet` - Parquet'
                                    ),
                                max_file_size_mb: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'If set, rolls to a new file once the current file exceeds this size in MB.'
                                    ),
                            })
                            .describe(
                                'Typed configuration for an Azure Blob Storage batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors\n`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating an Azure Blob Storage batch-export destination.'),
                zod
                    .object({
                        type: zod.enum(['BigQuery']),
                        integration_id: zod
                            .number()
                            .describe(
                                'ID of a google-cloud-service-account-kind Integration. Use the integrations-list MCP tool to find one.'
                            ),
                        config: zod
                            .object({
                                dataset_id: zod.string().describe('BigQuery dataset ID to write to.'),
                                table_id: zod
                                    .string()
                                    .default(batchExportsPartialUpdateBodyDestinationOneThreeConfigTableIdDefault)
                                    .describe('BigQuery table ID inside the dataset.'),
                                use_json_type: zod
                                    .boolean()
                                    .default(batchExportsPartialUpdateBodyDestinationOneThreeConfigUseJsonTypeDefault)
                                    .describe(
                                        "Whether to export 'properties', 'set', and 'set_once' fields as the BigQuery JSON type rather than STRING. Cannot be changed after the export is created."
                                    ),
                            })
                            .describe(
                                'Typed configuration for a BigQuery batch-export destination.\n\nCredentials live in the linked Integration, not in this config. Mirrors the\nnon-credential fields of `BigQueryBatchExportInputs` in\n`products/batch_exports/backend/service.py`.'
                            ),
                    })
                    .describe('Request shape for creating or updating a BigQuery batch-export destination.'),
            ])
            .optional()
            .describe('Destination configuration. Required integration_id is enforced per destination type.'),
        interval: zod
            .enum(['hour', 'day', 'week', 'every 5 minutes', 'every 15 minutes'])
            .describe(
                '* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            )
            .optional()
            .describe(
                'How often the batch export should run.\n\n* `hour` - hour\n* `day` - day\n* `week` - week\n* `every 5 minutes` - every 5 minutes\n* `every 15 minutes` - every 15 minutes'
            ),
        paused: zod.boolean().optional().describe('Whether the batch export is paused.'),
        timezone: zod
            .string()
            .nullish()
            .describe(
                "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries."
            ),
        offset_day: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetDayMin)
            .max(batchExportsPartialUpdateBodyOffsetDayMax)
            .nullish()
            .describe('Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).'),
        offset_hour: zod
            .number()
            .min(batchExportsPartialUpdateBodyOffsetHourMin)
            .max(batchExportsPartialUpdateBodyOffsetHourMax)
            .nullish()
            .describe('Hour-of-day offset (0-23) for daily and weekly intervals.'),
    })
    .describe(
        'Request body for create/partial_update on BatchExportViewSet.\n\nMirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic\n`destination` schema so integration_id is marked required on the types that need\nit. Responses continue to use `BatchExportSerializer`.'
    )

export const BatchExportsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch export.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create and start a batch export on demand run to download a file.
 */
export const FileDownloadBatchExportsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const fileDownloadBatchExportsCreateBodyOneFileFormatDefault = `Parquet`
export const fileDownloadBatchExportsCreateBodyOneFileMaxSizeMbMin = 0

export const fileDownloadBatchExportsCreateBodyTwoFileFormatDefault = `Parquet`
export const fileDownloadBatchExportsCreateBodyTwoFileMaxSizeMbMin = 0

export const fileDownloadBatchExportsCreateBodyThreeFileFormatDefault = `Parquet`
export const fileDownloadBatchExportsCreateBodyThreeFileMaxSizeMbMin = 0

export const FileDownloadBatchExportsCreateBody = /* @__PURE__ */ zod.union([
    zod
        .object({
            file: zod
                .object({
                    format: zod
                        .enum(['JSONLines', 'Parquet'])
                        .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                        .default(fileDownloadBatchExportsCreateBodyOneFileFormatDefault)
                        .describe('File format\n\n* `Parquet` - Parquet\n* `JSONLines` - JSONLines'),
                    compression: zod
                        .union([
                            zod
                                .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                .describe(
                                    '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Compress the file with a supported compression format\n\n* `zstd` - zstd\n* `gzip` - gzip\n* `brotli` - brotli\n* `lz4` - lz4\n* `snappy` - snappy'
                        ),
                    max_size_mb: zod
                        .number()
                        .min(fileDownloadBatchExportsCreateBodyOneFileMaxSizeMbMin)
                        .nullish()
                        .describe('Split download into multiple files of at most this size in MB'),
                })
                .describe('Typed configuration for a FileDownload batch-export destination.'),
            model: zod.enum(['events']),
            include: zod.array(zod.string()).optional(),
            exclude: zod.array(zod.string()).optional(),
            data_interval_start: zod.iso.datetime({ offset: true }),
            data_interval_end: zod.iso.datetime({ offset: true }),
        })
        .describe('Typed configuration for the events model.'),
    zod
        .object({
            file: zod
                .object({
                    format: zod
                        .enum(['JSONLines', 'Parquet'])
                        .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                        .default(fileDownloadBatchExportsCreateBodyTwoFileFormatDefault)
                        .describe('File format\n\n* `Parquet` - Parquet\n* `JSONLines` - JSONLines'),
                    compression: zod
                        .union([
                            zod
                                .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                .describe(
                                    '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Compress the file with a supported compression format\n\n* `zstd` - zstd\n* `gzip` - gzip\n* `brotli` - brotli\n* `lz4` - lz4\n* `snappy` - snappy'
                        ),
                    max_size_mb: zod
                        .number()
                        .min(fileDownloadBatchExportsCreateBodyTwoFileMaxSizeMbMin)
                        .nullish()
                        .describe('Split download into multiple files of at most this size in MB'),
                })
                .describe('Typed configuration for a FileDownload batch-export destination.'),
            model: zod.enum(['persons']),
            data_interval_start: zod.iso.datetime({ offset: true }),
            data_interval_end: zod.iso.datetime({ offset: true }),
        })
        .describe('Typed configuration for the persons model.'),
    zod
        .object({
            file: zod
                .object({
                    format: zod
                        .enum(['JSONLines', 'Parquet'])
                        .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                        .default(fileDownloadBatchExportsCreateBodyThreeFileFormatDefault)
                        .describe('File format\n\n* `Parquet` - Parquet\n* `JSONLines` - JSONLines'),
                    compression: zod
                        .union([
                            zod
                                .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                                .describe(
                                    '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                                ),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'Compress the file with a supported compression format\n\n* `zstd` - zstd\n* `gzip` - gzip\n* `brotli` - brotli\n* `lz4` - lz4\n* `snappy` - snappy'
                        ),
                    max_size_mb: zod
                        .number()
                        .min(fileDownloadBatchExportsCreateBodyThreeFileMaxSizeMbMin)
                        .nullish()
                        .describe('Split download into multiple files of at most this size in MB'),
                })
                .describe('Typed configuration for a FileDownload batch-export destination.'),
            model: zod.enum(['sessions']),
            data_interval_start: zod.iso.datetime({ offset: true }),
            data_interval_end: zod.iso.datetime({ offset: true }),
        })
        .describe('Typed configuration for the sessions model.'),
])

/**
 * Get a batch export on demand run.

If the underlying batch export run has completed, we return keys to the
generated file downloads so that users may download them by making a request
to /download.
 */
export const FileDownloadBatchExportsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch export run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Cancel an ongoing file-download batch export.
 */
export const FileDownloadBatchExportsCancelCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this batch export run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const fileDownloadBatchExportsCancelCreateBodyFileFormatDefault = `Parquet`
export const fileDownloadBatchExportsCancelCreateBodyFileMaxSizeMbMin = 0

export const FileDownloadBatchExportsCancelCreateBody = /* @__PURE__ */ zod
    .object({
        file: zod
            .object({
                format: zod
                    .enum(['JSONLines', 'Parquet'])
                    .describe('* `JSONLines` - JSONLines\n* `Parquet` - Parquet')
                    .default(fileDownloadBatchExportsCancelCreateBodyFileFormatDefault)
                    .describe('File format\n\n* `Parquet` - Parquet\n* `JSONLines` - JSONLines'),
                compression: zod
                    .union([
                        zod
                            .enum(['brotli', 'gzip', 'lz4', 'snappy', 'zstd'])
                            .describe(
                                '* `brotli` - brotli\n* `gzip` - gzip\n* `lz4` - lz4\n* `snappy` - snappy\n* `zstd` - zstd'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'Compress the file with a supported compression format\n\n* `zstd` - zstd\n* `gzip` - gzip\n* `brotli` - brotli\n* `lz4` - lz4\n* `snappy` - snappy'
                    ),
                max_size_mb: zod
                    .number()
                    .min(fileDownloadBatchExportsCancelCreateBodyFileMaxSizeMbMin)
                    .nullish()
                    .describe('Split download into multiple files of at most this size in MB'),
            })
            .describe('Typed configuration for a FileDownload batch-export destination.'),
        model: zod
            .enum(['events', 'persons', 'sessions'])
            .describe('* `events` - events\n* `persons` - persons\n* `sessions` - sessions'),
        include: zod.array(zod.string()).optional(),
        exclude: zod.array(zod.string()).optional(),
        data_interval_start: zod.iso.datetime({ offset: true }),
        data_interval_end: zod.iso.datetime({ offset: true }),
    })
    .describe('Request shape for a FileDownload batch export on demand.')
