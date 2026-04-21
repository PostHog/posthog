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
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const AlertsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const alertsCreateBodyConfigOneTypeDefault = `TrendsAlertConfig`
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
            created_at: zod.iso.datetime({}).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .object({
                            lower: zod
                                .number()
                                .nullish()
                                .describe('Alert fires when the value drops below this number.'),
                            upper: zod.number().nullish().describe('Alert fires when the value exceeds this number.'),
                        })
                        .nullish(),
                    type: zod.enum(['absolute', 'percentage']),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
                ),
        })
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .object({
            type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
        })
        .nullish()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .object({
            check_ongoing_interval: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                ),
            series_index: zod.number().describe("Zero-based index of the series in the insight's query to monitor."),
            type: zod.enum(['TrendsAlertConfig']).default(alertsCreateBodyConfigOneTypeDefault),
        })
        .nullish()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
        ),
    detector_config: zod
        .union([
            zod.object({
                detectors: zod
                    .array(
                        zod.union([
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['iqr'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['threshold'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                                nu: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']),
                type: zod.enum(['ensemble']).default(alertsCreateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .number()
                    .nullish()
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['iqr']).default(alertsCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod.number().nullish().describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['threshold']).default(alertsCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod.number().nullish().describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod.number().nullish().describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                n_neighbors: zod.number().nullish().describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod.number().nullish().describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                nu: zod.number().nullish().describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
        ])
        .describe('Detector configuration types')
        .nullish(),
    calculation_interval: zod
        .enum(['hourly', 'daily', 'weekly', 'monthly'])
        .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly')
        .optional()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
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
        .object({
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
        })
        .nullish()
        .describe(
            'Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables.'
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

export const alertsPartialUpdateBodyConfigOneTypeDefault = `TrendsAlertConfig`
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
            created_at: zod.iso.datetime({}).optional(),
            name: zod.string().optional().describe('Optional name for the threshold.'),
            configuration: zod
                .object({
                    bounds: zod
                        .object({
                            lower: zod
                                .number()
                                .nullish()
                                .describe('Alert fires when the value drops below this number.'),
                            upper: zod.number().nullish().describe('Alert fires when the value exceeds this number.'),
                        })
                        .nullish(),
                    type: zod.enum(['absolute', 'percentage']),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
                ),
        })
        .optional()
        .describe('Threshold configuration with bounds and type for evaluating the alert.'),
    condition: zod
        .object({
            type: zod.enum(['absolute_value', 'relative_increase', 'relative_decrease']),
        })
        .nullish()
        .describe(
            'Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.'
        ),
    enabled: zod.boolean().optional().describe('Whether the alert is actively being evaluated.'),
    config: zod
        .object({
            check_ongoing_interval: zod
                .boolean()
                .nullish()
                .describe(
                    'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                ),
            series_index: zod.number().describe("Zero-based index of the series in the insight's query to monitor."),
            type: zod.enum(['TrendsAlertConfig']).default(alertsPartialUpdateBodyConfigOneTypeDefault),
        })
        .nullish()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
        ),
    detector_config: zod
        .union([
            zod.object({
                detectors: zod
                    .array(
                        zod.union([
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['iqr'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['threshold'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(
                                        alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                                nu: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']),
                type: zod.enum(['ensemble']).default(alertsPartialUpdateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .number()
                    .nullish()
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['iqr']).default(alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod.number().nullish().describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['threshold']).default(alertsPartialUpdateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod.number().nullish().describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsPartialUpdateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsPartialUpdateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod.number().nullish().describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsPartialUpdateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                n_neighbors: zod.number().nullish().describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsPartialUpdateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsPartialUpdateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod.number().nullish().describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsPartialUpdateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                nu: zod.number().nullish().describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsPartialUpdateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsPartialUpdateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
        ])
        .describe('Detector configuration types')
        .nullish(),
    calculation_interval: zod
        .enum(['hourly', 'daily', 'weekly', 'monthly'])
        .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly')
        .optional()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
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
        .object({
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
        })
        .nullish()
        .describe(
            'Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables.'
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
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['iqr'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['threshold'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                                nu: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']),
                type: zod.enum(['ensemble']).default(alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .number()
                    .nullish()
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['iqr']).default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod.number().nullish().describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod.number().nullish().describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['threshold']).default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod.number().nullish().describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod.number().nullish().describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                n_neighbors: zod.number().nullish().describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod.number().nullish().describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod.number().nullish().describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.string().nullish().describe('SVM kernel type (default: "rbf")'),
                nu: zod.number().nullish().describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod.number().nullish().describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .number()
                    .nullish()
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
        .describe('Zero-based index of the series to analyze.'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples."
        ),
})
