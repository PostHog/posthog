/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const AlertsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AlertsListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod
        .string()
        .optional()
        .describe('Optional. Restrict results to alerts created by the user with this UUID.'),
    insight_id: zod.number().optional().describe('Optional. Restrict results to alerts on this insight ID.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod
        .string()
        .optional()
        .describe(
            'Optional. Fuzzy match against alert `name` using Postgres trigram word similarity (handles typos, transpositions, and prefix-as-you-type). Results are ordered by relevance, then creation time. Capped at 200 characters; longer queries return a 400 error.'
        ),
})

export const AlertsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsCreateBodyConfigOneOneTypeDefault = `TrendsAlertConfig`
export const alertsCreateBodyConfigOneTwoTypeDefault = `HogQLAlertConfig`
export const alertsCreateBodyConfigOneThreeTypeDefault = `FunnelsAlertConfig`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`

export const AlertsCreateBody = /* @__PURE__ */ zod.object({
    insight: zod
        .number()
        .describe('Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.'),
    name: zod.string().optional().describe('Human-readable name for the alert.'),
    subscribed_users: zod
        .array(zod.number())
        .describe('User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.'),
    threshold: zod
        .object({
            id: zod.string().optional(),
            created_at: zod.iso.datetime({ offset: true }).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .union([
                            zod.object({
                                lower: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Alert fires when the value drops below this number.'),
                                upper: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Alert fires when the value exceeds this number.'),
                            }),
                            zod.null(),
                        ])
                        .optional(),
                    type: zod
                        .enum(['absolute', 'percentage'])
                        .describe(
                            'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                        ),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage). For threshold-based alerts (no detector_config), at least one of lower or upper must be set.'
                ),
        })
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .union([
            zod.object({
                type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .union([
            zod
                .union([
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                            ),
                        series_index: zod
                            .number()
                            .describe("Zero-based index of the series in the insight's query to monitor."),
                        type: zod.enum(['TrendsAlertConfig']).default(alertsCreateBodyConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column).'
                            ),
                        evaluation: zod
                            .enum(['last_row', 'first_row', 'any_row'])
                            .describe('How to read the result rows — an explicit choice, no implicit default.'),
                        label_column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row/first_row).'
                            ),
                        type: zod.enum(['HogQLAlertConfig']).default(alertsCreateBodyConfigOneTwoTypeDefault),
                    }),
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still in-progress) period; by default only completed periods are used.'
                            ),
                        funnel_step: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Zero-based step index to evaluate. Null = the last step (overall conversion).'),
                        metric: zod.enum(['conversion_from_start', 'conversion_from_previous']),
                        type: zod.enum(['FunnelsAlertConfig']).default(alertsCreateBodyConfigOneThreeTypeDefault),
                    }),
                ])
                .describe(
                    'Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the\ngenerated frontend types and MCP tool schemas) in sync with every kind alerts support.'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            "Per-insight-kind alert configuration, discriminated by `type`. TrendsAlertConfig: series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). HogQLAlertConfig (SQL insights): column (which result column to evaluate, defaults to the single numeric column), evaluation ('last_row' checks the latest value of an oldest->newest query, 'first_row' checks the first value of a newest->oldest query, 'any_row' fires if any row breaches), and label_column (names the evaluated row(s) in breach messages, in every evaluation mode). FunnelsAlertConfig (funnel insights): funnel_step (the step to monitor, null for the overall last step), metric ('conversion_from_start' or 'conversion_from_previous'), and check_ongoing_interval (historical-trend funnels: also evaluate the current in-progress period). Steps funnels support only absolute_value conditions; historical-trend funnels also support relative_increase/relative_decrease (compared against the prior period)."
        ),
    detector_config: zod
        .union([
            zod
                .union([
                    zod.object({
                        detectors: zod
                            .array(
                                zod.union([
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('zscore')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('mad')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                                    }),
                                    zod.object({
                                        multiplier: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                            ),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('iqr')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                                    }),
                                    zod.object({
                                        lower_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Lower bound - values below this are anomalies'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('threshold')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                        upper_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Upper bound - values above this are anomalies'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ecod')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('copod')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_estimators: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of trees in the forest (default: 100)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('isolation_forest')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        method: zod
                                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                            .optional()
                                            .describe(
                                                "Distance method: 'largest', 'mean', 'median' (default: 'largest')"
                                            ),
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of neighbors to consider (default: 5)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('knn')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_bins: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of histogram bins (default: 10)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('hbos')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of neighbors for LOF (default: 20)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('lof')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        kernel: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe('SVM kernel type (default: "rbf")'),
                                        nu: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ocsvm')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('pca')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                ])
                            )
                            .describe('Sub-detector configurations (minimum 2)'),
                        operator: zod.enum(['and', 'or']).describe('How to combine sub-detector results'),
                        type: zod.literal('ensemble').default(alertsCreateBodyDetectorConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('zscore').default(alertsCreateBodyDetectorConfigOneTwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('mad').default(alertsCreateBodyDetectorConfigOneThreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                    }),
                    zod.object({
                        multiplier: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('iqr').default(alertsCreateBodyDetectorConfigOneFourTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                    }),
                    zod.object({
                        lower_bound: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Lower bound - values below this are anomalies'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('threshold').default(alertsCreateBodyDetectorConfigOneFiveTypeDefault),
                        upper_bound: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Upper bound - values above this are anomalies'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ecod').default(alertsCreateBodyDetectorConfigOneSixTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('copod').default(alertsCreateBodyDetectorConfigOneSevenTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_estimators: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of trees in the forest (default: 100)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod
                            .literal('isolation_forest')
                            .default(alertsCreateBodyDetectorConfigOneEightTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        method: zod
                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                            .optional()
                            .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of neighbors to consider (default: 5)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('knn').default(alertsCreateBodyDetectorConfigOneNineTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_bins: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of histogram bins (default: 10)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('hbos').default(alertsCreateBodyDetectorConfigOneOnezeroTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of neighbors for LOF (default: 20)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('lof').default(alertsCreateBodyDetectorConfigOneOneoneTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        kernel: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe('SVM kernel type (default: "rbf")'),
                        nu: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ocsvm').default(alertsCreateBodyDetectorConfigOneOnetwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('pca').default(alertsCreateBodyDetectorConfigOneOnethreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                ])
                .describe('Detector configuration types'),
            zod.null(),
        ])
        .optional(),
    calculation_interval: zod
        .enum(['every_15_minutes', 'hourly', 'daily', 'weekly', 'monthly'])
        .describe(
            '* `every_15_minutes` - every_15_minutes\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        )
        .optional()
        .describe(
            'How often the alert is checked: every 15 minutes (Boost+), hourly, daily, weekly, or monthly.\n\n* `every_15_minutes` - every_15_minutes\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod
        .boolean()
        .nullish()
        .describe('Skip alert evaluation on weekends (Saturday and Sunday, local to project timezone).'),
    schedule_restriction: zod
        .union([
            zod.object({
                blocked_windows: zod
                    .array(
                        zod.object({
                            start: zod
                                .string()
                                .describe(
                                    'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                ),
                            end: zod
                                .string()
                                .describe(
                                    'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                ),
                        })
                    )
                    .describe(
                        'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables.'
        ),
    investigation_agent_enabled: zod
        .boolean()
        .optional()
        .describe(
            'When enabled, an investigation agent runs on the state transition to firing and writes findings to a Notebook linked from the alert check. Only effective for detector-based (anomaly) alerts.'
        ),
    investigation_gates_notifications: zod
        .boolean()
        .optional()
        .describe(
            'When enabled (and investigation_agent_enabled is on), notification dispatch is held until the investigation agent produces a verdict. Notifications are suppressed when the verdict is false_positive (and optionally when inconclusive). A safety-net task force-fires after a few minutes if the investigation stalls.'
        ),
    investigation_inconclusive_action: zod
        .enum(['notify', 'suppress'])
        .describe('* `notify` - Notify\n* `suppress` - Suppress')
        .optional()
        .describe(
            "How to handle an 'inconclusive' verdict when notifications are gated. 'notify' is the safe default — an agent that can't be sure is itself useful signal.\n\n* `notify` - Notify\n* `suppress` - Suppress"
        ),
})

export const AlertsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AlertsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    checks_date_from: zod
        .string()
        .optional()
        .describe(
            "Relative date string for the start of the check history window (e.g. '-24h', '-7d', '-14d'). Returns checks created after this time. Max retention is 14 days."
        ),
    checks_date_to: zod
        .string()
        .optional()
        .describe(
            "Relative date string for the end of the check history window (e.g. '-1h', '-1d'). Defaults to now if not specified."
        ),
    checks_limit: zod
        .number()
        .optional()
        .describe('Maximum number of check results to return (default 5, max 500). Applied after date filtering.'),
    checks_offset: zod
        .number()
        .optional()
        .describe('Number of newest checks to skip (0-based). Use with checks_limit for pagination. Default 0.'),
})

export const AlertsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsPartialUpdateBodyConfigOneOneTypeDefault = `TrendsAlertConfig`
export const alertsPartialUpdateBodyConfigOneTwoTypeDefault = `HogQLAlertConfig`
export const alertsPartialUpdateBodyConfigOneThreeTypeDefault = `FunnelsAlertConfig`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsPartialUpdateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsPartialUpdateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsPartialUpdateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsPartialUpdateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsPartialUpdateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsPartialUpdateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsPartialUpdateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsPartialUpdateBodyDetectorConfigOneOnethreeTypeDefault = `pca`

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    insight: zod
        .number()
        .optional()
        .describe('Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.'),
    name: zod.string().optional().describe('Human-readable name for the alert.'),
    subscribed_users: zod
        .array(zod.number())
        .optional()
        .describe('User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.'),
    threshold: zod
        .object({
            id: zod.string().optional(),
            created_at: zod.iso.datetime({ offset: true }).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .union([
                            zod.object({
                                lower: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Alert fires when the value drops below this number.'),
                                upper: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Alert fires when the value exceeds this number.'),
                            }),
                            zod.null(),
                        ])
                        .optional(),
                    type: zod
                        .enum(['absolute', 'percentage'])
                        .describe(
                            'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                        ),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage). For threshold-based alerts (no detector_config), at least one of lower or upper must be set.'
                ),
        })
        .optional()
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .union([
            zod.object({
                type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .union([
            zod
                .union([
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                            ),
                        series_index: zod
                            .number()
                            .describe("Zero-based index of the series in the insight's query to monitor."),
                        type: zod.enum(['TrendsAlertConfig']).default(alertsPartialUpdateBodyConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column).'
                            ),
                        evaluation: zod
                            .enum(['last_row', 'first_row', 'any_row'])
                            .describe('How to read the result rows — an explicit choice, no implicit default.'),
                        label_column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row/first_row).'
                            ),
                        type: zod.enum(['HogQLAlertConfig']).default(alertsPartialUpdateBodyConfigOneTwoTypeDefault),
                    }),
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still in-progress) period; by default only completed periods are used.'
                            ),
                        funnel_step: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Zero-based step index to evaluate. Null = the last step (overall conversion).'),
                        metric: zod.enum(['conversion_from_start', 'conversion_from_previous']),
                        type: zod
                            .enum(['FunnelsAlertConfig'])
                            .default(alertsPartialUpdateBodyConfigOneThreeTypeDefault),
                    }),
                ])
                .describe(
                    'Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the\ngenerated frontend types and MCP tool schemas) in sync with every kind alerts support.'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            "Per-insight-kind alert configuration, discriminated by `type`. TrendsAlertConfig: series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval). HogQLAlertConfig (SQL insights): column (which result column to evaluate, defaults to the single numeric column), evaluation ('last_row' checks the latest value of an oldest->newest query, 'first_row' checks the first value of a newest->oldest query, 'any_row' fires if any row breaches), and label_column (names the evaluated row(s) in breach messages, in every evaluation mode). FunnelsAlertConfig (funnel insights): funnel_step (the step to monitor, null for the overall last step), metric ('conversion_from_start' or 'conversion_from_previous'), and check_ongoing_interval (historical-trend funnels: also evaluate the current in-progress period). Steps funnels support only absolute_value conditions; historical-trend funnels also support relative_increase/relative_decrease (compared against the prior period)."
        ),
    detector_config: zod
        .union([
            zod
                .union([
                    zod.object({
                        detectors: zod
                            .array(
                                zod.union([
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('zscore')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('mad')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                                    }),
                                    zod.object({
                                        multiplier: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                            ),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('iqr')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                                    }),
                                    zod.object({
                                        lower_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Lower bound - values below this are anomalies'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('threshold')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault
                                            ),
                                        upper_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Upper bound - values above this are anomalies'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ecod')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('copod')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_estimators: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of trees in the forest (default: 100)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('isolation_forest')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        method: zod
                                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                            .optional()
                                            .describe(
                                                "Distance method: 'largest', 'mean', 'median' (default: 'largest')"
                                            ),
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of neighbors to consider (default: 5)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('knn')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_bins: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of histogram bins (default: 10)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('hbos')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Number of neighbors for LOF (default: 20)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('lof')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        kernel: zod
                                            .union([zod.string(), zod.null()])
                                            .optional()
                                            .describe('SVM kernel type (default: "rbf")'),
                                        nu: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ocsvm')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .optional()
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .optional()
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('pca')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .optional()
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                ])
                            )
                            .describe('Sub-detector configurations (minimum 2)'),
                        operator: zod.enum(['and', 'or']).describe('How to combine sub-detector results'),
                        type: zod.literal('ensemble').default(alertsPartialUpdateBodyDetectorConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('zscore').default(alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('mad').default(alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                    }),
                    zod.object({
                        multiplier: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('iqr').default(alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                    }),
                    zod.object({
                        lower_bound: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Lower bound - values below this are anomalies'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('threshold').default(alertsPartialUpdateBodyDetectorConfigOneFiveTypeDefault),
                        upper_bound: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Upper bound - values above this are anomalies'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ecod').default(alertsPartialUpdateBodyDetectorConfigOneSixTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('copod').default(alertsPartialUpdateBodyDetectorConfigOneSevenTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_estimators: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of trees in the forest (default: 100)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod
                            .literal('isolation_forest')
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        method: zod
                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                            .optional()
                            .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of neighbors to consider (default: 5)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('knn').default(alertsPartialUpdateBodyDetectorConfigOneNineTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_bins: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of histogram bins (default: 10)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('hbos').default(alertsPartialUpdateBodyDetectorConfigOneOnezeroTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Number of neighbors for LOF (default: 20)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('lof').default(alertsPartialUpdateBodyDetectorConfigOneOneoneTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        kernel: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe('SVM kernel type (default: "rbf")'),
                        nu: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ocsvm').default(alertsPartialUpdateBodyDetectorConfigOneOnetwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .optional()
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('pca').default(alertsPartialUpdateBodyDetectorConfigOneOnethreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                ])
                .describe('Detector configuration types'),
            zod.null(),
        ])
        .optional(),
    calculation_interval: zod
        .enum(['every_15_minutes', 'hourly', 'daily', 'weekly', 'monthly'])
        .describe(
            '* `every_15_minutes` - every_15_minutes\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        )
        .optional()
        .describe(
            'How often the alert is checked: every 15 minutes (Boost+), hourly, daily, weekly, or monthly.\n\n* `every_15_minutes` - every_15_minutes\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod
        .boolean()
        .nullish()
        .describe('Skip alert evaluation on weekends (Saturday and Sunday, local to project timezone).'),
    schedule_restriction: zod
        .union([
            zod.object({
                blocked_windows: zod
                    .array(
                        zod.object({
                            start: zod
                                .string()
                                .describe(
                                    'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                ),
                            end: zod
                                .string()
                                .describe(
                                    'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                ),
                        })
                    )
                    .describe(
                        'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables.'
        ),
    investigation_agent_enabled: zod
        .boolean()
        .optional()
        .describe(
            'When enabled, an investigation agent runs on the state transition to firing and writes findings to a Notebook linked from the alert check. Only effective for detector-based (anomaly) alerts.'
        ),
    investigation_gates_notifications: zod
        .boolean()
        .optional()
        .describe(
            'When enabled (and investigation_agent_enabled is on), notification dispatch is held until the investigation agent produces a verdict. Notifications are suppressed when the verdict is false_positive (and optionally when inconclusive). A safety-net task force-fires after a few minutes if the investigation stalls.'
        ),
    investigation_inconclusive_action: zod
        .enum(['notify', 'suppress'])
        .describe('* `notify` - Notify\n* `suppress` - Suppress')
        .optional()
        .describe(
            "How to handle an 'inconclusive' verdict when notifications are gated. 'notify' is the safe default — an agent that can't be sure is itself useful signal.\n\n* `notify` - Notify\n* `suppress` - Suppress"
        ),
})

export const AlertsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const AlertsSimulateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsSimulateCreateBodySeriesIndexDefault = 0
export const alertsSimulateCreateBodyConfigOneOneTypeDefault = `TrendsAlertConfig`
export const alertsSimulateCreateBodyConfigOneTwoTypeDefault = `HogQLAlertConfig`
export const alertsSimulateCreateBodyConfigOneThreeTypeDefault = `FunnelsAlertConfig`

export const AlertsSimulateCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number().describe('Insight ID to simulate the detector on.'),
    detector_config: zod
        .union([
            zod.object({
                detectors: zod
                    .array(
                        zod.union([
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .literal('zscore')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .literal('mad')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .literal('iqr')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .literal('threshold')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('ecod')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('copod')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('isolation_forest')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod
                                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                    .optional()
                                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('knn')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('hbos')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('lof')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe('SVM kernel type (default: "rbf")'),
                                nu: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('ocsvm')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('pca')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']).describe('How to combine sub-detector results'),
                type: zod.literal('ensemble').default(alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.literal('zscore').default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.literal('mad').default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.literal('iqr').default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.literal('threshold').default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('ecod').default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('copod').default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod
                    .literal('isolation_forest')
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod
                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                    .optional()
                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('knn').default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('hbos').default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('lof').default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.union([zod.string(), zod.null()]).optional().describe('SVM kernel type (default: "rbf")'),
                nu: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('ocsvm').default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('pca').default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
        ])
        .describe('Detector configuration types')
        .describe('Detector configuration to simulate.'),
    series_index: zod
        .number()
        .default(alertsSimulateCreateBodySeriesIndexDefault)
        .describe('Zero-based index of the series to analyze (trends insights only).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples. Trends insights only — a SQL query's own rows are the series."
        ),
    config: zod
        .union([
            zod
                .union([
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                            ),
                        series_index: zod
                            .number()
                            .describe("Zero-based index of the series in the insight's query to monitor."),
                        type: zod.enum(['TrendsAlertConfig']).default(alertsSimulateCreateBodyConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column).'
                            ),
                        evaluation: zod
                            .enum(['last_row', 'first_row', 'any_row'])
                            .describe('How to read the result rows — an explicit choice, no implicit default.'),
                        label_column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row/first_row).'
                            ),
                        type: zod.enum(['HogQLAlertConfig']).default(alertsSimulateCreateBodyConfigOneTwoTypeDefault),
                    }),
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still in-progress) period; by default only completed periods are used.'
                            ),
                        funnel_step: zod
                            .union([zod.number(), zod.null()])
                            .optional()
                            .describe('Zero-based step index to evaluate. Null = the last step (overall conversion).'),
                        metric: zod.enum(['conversion_from_start', 'conversion_from_previous']),
                        type: zod
                            .enum(['FunnelsAlertConfig'])
                            .default(alertsSimulateCreateBodyConfigOneThreeTypeDefault),
                    }),
                ])
                .describe(
                    'Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the\ngenerated frontend types and MCP tool schemas) in sync with every kind alerts support.'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Per-insight-kind alert config. For SQL insights, selects the evaluated column and read direction (last_row/first_row) so the preview matches the alert; ignored for trends.'
        ),
})
