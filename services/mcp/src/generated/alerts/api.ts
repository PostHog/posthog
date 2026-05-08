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

export const alertsCreateBodyThresholdOneConfigurationOneBoundsOneLowerDefault = null
export const alertsCreateBodyThresholdOneConfigurationOneBoundsOneUpperDefault = null
export const alertsCreateBodyThresholdOneConfigurationOneBoundsDefault = null
export const alertsCreateBodyConfigOneCheckOngoingIntervalDefault = null
export const alertsCreateBodyConfigOneTypeDefault = `TrendsAlertConfig`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsCreateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneTwoPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneTwoThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsCreateBodyDetectorConfigOneTwoWindowDefault = null
export const alertsCreateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneThreePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneThreeThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsCreateBodyDetectorConfigOneThreeWindowDefault = null
export const alertsCreateBodyDetectorConfigOneFourMultiplierDefault = null
export const alertsCreateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneFourPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsCreateBodyDetectorConfigOneFourWindowDefault = null
export const alertsCreateBodyDetectorConfigOneFiveLowerBoundDefault = null
export const alertsCreateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneFivePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsCreateBodyDetectorConfigOneFiveUpperBoundDefault = null
export const alertsCreateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneSixPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneSixThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsCreateBodyDetectorConfigOneSixWindowDefault = null
export const alertsCreateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneSevenPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneSevenThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsCreateBodyDetectorConfigOneSevenWindowDefault = null
export const alertsCreateBodyDetectorConfigOneEightNEstimatorsDefault = null
export const alertsCreateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneEightPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneEightThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsCreateBodyDetectorConfigOneEightWindowDefault = null
export const alertsCreateBodyDetectorConfigOneNineMethodDefault = null
export const alertsCreateBodyDetectorConfigOneNineNNeighborsDefault = null
export const alertsCreateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneNinePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneNineThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsCreateBodyDetectorConfigOneNineWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroNBinsDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsCreateBodyDetectorConfigOneOnezeroWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOneoneNNeighborsDefault = null
export const alertsCreateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOneonePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOneoneThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsCreateBodyDetectorConfigOneOneoneWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoKernelDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoNuDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoPreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsCreateBodyDetectorConfigOneOnetwoWindowDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreePreprocessingDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreeThresholdDefault = null
export const alertsCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsCreateBodyDetectorConfigOneOnethreeWindowDefault = null

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
                                    .default(alertsCreateBodyThresholdOneConfigurationOneBoundsOneLowerDefault)
                                    .describe('Alert fires when the value drops below this number.'),
                                upper: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsCreateBodyThresholdOneConfigurationOneBoundsOneUpperDefault)
                                    .describe('Alert fires when the value exceeds this number.'),
                            }),
                            zod.null(),
                        ])
                        .default(alertsCreateBodyThresholdOneConfigurationOneBoundsDefault),
                    type: zod
                        .enum(['absolute', 'percentage'])
                        .describe(
                            'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                        ),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
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
            zod.object({
                check_ongoing_interval: zod
                    .union([zod.boolean(), zod.null()])
                    .default(alertsCreateBodyConfigOneCheckOngoingIntervalDefault)
                    .describe(
                        'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                    ),
                series_index: zod
                    .number()
                    .describe("Zero-based index of the series in the insight's query to monitor."),
                type: zod.literal('TrendsAlertConfig').default(alertsCreateBodyConfigOneTypeDefault),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
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
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault
                                            )
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('zscore')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault)
                                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault
                                            )
                                            .describe(
                                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                            ),
                                        type: zod
                                            .literal('mad')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault)
                                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                                    }),
                                    zod.object({
                                        multiplier: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault
                                            )
                                            .describe(
                                                'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                            ),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('iqr')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault
                                            )
                                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                                    }),
                                    zod.object({
                                        lower_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault
                                            )
                                            .describe('Lower bound - values below this are anomalies'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('threshold')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                        upper_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault
                                            )
                                            .describe('Upper bound - values above this are anomalies'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ecod')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault)
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
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('copod')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault)
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_estimators: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault
                                            )
                                            .describe('Number of trees in the forest (default: 100)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('isolation_forest')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        method: zod
                                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault
                                            )
                                            .describe(
                                                "Distance method: 'largest', 'mean', 'median' (default: 'largest')"
                                            ),
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault
                                            )
                                            .describe('Number of neighbors to consider (default: 5)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('knn')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_bins: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault)
                                            .describe('Number of histogram bins (default: 10)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('hbos')
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault)
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault
                                            )
                                            .describe('Number of neighbors for LOF (default: 20)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('lof')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        kernel: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault
                                            )
                                            .describe('SVM kernel type (default: "rbf")'),
                                        nu: zod
                                            .union([zod.number(), zod.null()])
                                            .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault)
                                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ocsvm')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault
                                            )
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
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('pca')
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault
                                            )
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
                                        .default(alertsCreateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneTwoPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneTwoThresholdDefault)
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('zscore').default(alertsCreateBodyDetectorConfigOneTwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneTwoWindowDefault)
                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneThreePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneThreeThresholdDefault)
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('mad').default(alertsCreateBodyDetectorConfigOneThreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneThreeWindowDefault)
                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                    }),
                    zod.object({
                        multiplier: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneFourMultiplierDefault)
                            .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneFourPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('iqr').default(alertsCreateBodyDetectorConfigOneFourTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneFourWindowDefault)
                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                    }),
                    zod.object({
                        lower_bound: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneFiveLowerBoundDefault)
                            .describe('Lower bound - values below this are anomalies'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneFivePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('threshold').default(alertsCreateBodyDetectorConfigOneFiveTypeDefault),
                        upper_bound: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneFiveUpperBoundDefault)
                            .describe('Upper bound - values above this are anomalies'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneSixPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneSixThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ecod').default(alertsCreateBodyDetectorConfigOneSixTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneSixWindowDefault)
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
                                        .default(alertsCreateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneSevenPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneSevenThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('copod').default(alertsCreateBodyDetectorConfigOneSevenTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneSevenWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_estimators: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneEightNEstimatorsDefault)
                            .describe('Number of trees in the forest (default: 100)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneEightPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneEightThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod
                            .literal('isolation_forest')
                            .default(alertsCreateBodyDetectorConfigOneEightTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneEightWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        method: zod
                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneNineMethodDefault)
                            .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneNineNNeighborsDefault)
                            .describe('Number of neighbors to consider (default: 5)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneNinePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneNineThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('knn').default(alertsCreateBodyDetectorConfigOneNineTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneNineWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_bins: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnezeroNBinsDefault)
                            .describe('Number of histogram bins (default: 10)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneOnezeroPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnezeroThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('hbos').default(alertsCreateBodyDetectorConfigOneOnezeroTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnezeroWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOneoneNNeighborsDefault)
                            .describe('Number of neighbors for LOF (default: 20)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneOneonePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOneoneThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('lof').default(alertsCreateBodyDetectorConfigOneOneoneTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOneoneWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        kernel: zod
                            .union([zod.string(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnetwoKernelDefault)
                            .describe('SVM kernel type (default: "rbf")'),
                        nu: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnetwoNuDefault)
                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault)
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneOnetwoPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnetwoThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ocsvm').default(alertsCreateBodyDetectorConfigOneOnetwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnetwoWindowDefault)
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
                                        .default(alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault)
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault)
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsCreateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsCreateBodyDetectorConfigOneOnethreePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnethreeThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('pca').default(alertsCreateBodyDetectorConfigOneOnethreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsCreateBodyDetectorConfigOneOnethreeWindowDefault)
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

export const alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsOneLowerDefault = null
export const alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsOneUpperDefault = null
export const alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsDefault = null
export const alertsPartialUpdateBodyConfigOneCheckOngoingIntervalDefault = null
export const alertsPartialUpdateBodyConfigOneTypeDefault = `TrendsAlertConfig`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneTwoThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsPartialUpdateBodyDetectorConfigOneTwoWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreeThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsPartialUpdateBodyDetectorConfigOneThreeWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourMultiplierDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsPartialUpdateBodyDetectorConfigOneFourWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFiveLowerBoundDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsPartialUpdateBodyDetectorConfigOneFiveUpperBoundDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsPartialUpdateBodyDetectorConfigOneSixWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsPartialUpdateBodyDetectorConfigOneSevenWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightNEstimatorsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsPartialUpdateBodyDetectorConfigOneEightWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNineMethodDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNineNNeighborsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNineThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsPartialUpdateBodyDetectorConfigOneNineWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroNBinsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsPartialUpdateBodyDetectorConfigOneOnezeroWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneoneNNeighborsDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneoneThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsPartialUpdateBodyDetectorConfigOneOneoneWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoKernelDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoNuDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsPartialUpdateBodyDetectorConfigOneOnetwoWindowDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreeThresholdDefault = null
export const alertsPartialUpdateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsPartialUpdateBodyDetectorConfigOneOnethreeWindowDefault = null

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
                                    .default(alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsOneLowerDefault)
                                    .describe('Alert fires when the value drops below this number.'),
                                upper: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsOneUpperDefault)
                                    .describe('Alert fires when the value exceeds this number.'),
                            }),
                            zod.null(),
                        ])
                        .default(alertsPartialUpdateBodyThresholdOneConfigurationOneBoundsDefault),
                    type: zod
                        .enum(['absolute', 'percentage'])
                        .describe(
                            'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
                        ),
                })
                .describe(
                    'Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).'
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
            zod.object({
                check_ongoing_interval: zod
                    .union([zod.boolean(), zod.null()])
                    .default(alertsPartialUpdateBodyConfigOneCheckOngoingIntervalDefault)
                    .describe(
                        'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                    ),
                series_index: zod
                    .number()
                    .describe("Zero-based index of the series in the insight's query to monitor."),
                type: zod.literal('TrendsAlertConfig').default(alertsPartialUpdateBodyConfigOneTypeDefault),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).'
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
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault
                                            )
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
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault
                                            )
                                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault
                                            )
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
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault
                                            )
                                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                                    }),
                                    zod.object({
                                        multiplier: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault
                                            )
                                            .describe(
                                                'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                            ),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('iqr')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault
                                            )
                                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                                    }),
                                    zod.object({
                                        lower_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault
                                            )
                                            .describe('Lower bound - values below this are anomalies'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        type: zod
                                            .literal('threshold')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault
                                            ),
                                        upper_bound: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault
                                            )
                                            .describe('Upper bound - values above this are anomalies'),
                                    }),
                                    zod.object({
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ecod')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault
                                            )
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
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('copod')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_estimators: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault
                                            )
                                            .describe('Number of trees in the forest (default: 100)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('isolation_forest')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        method: zod
                                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault
                                            )
                                            .describe(
                                                "Distance method: 'largest', 'mean', 'median' (default: 'largest')"
                                            ),
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault
                                            )
                                            .describe('Number of neighbors to consider (default: 5)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('knn')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_bins: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault
                                            )
                                            .describe('Number of histogram bins (default: 10)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('hbos')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        n_neighbors: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault
                                            )
                                            .describe('Number of neighbors for LOF (default: 20)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('lof')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault
                                            )
                                            .describe(
                                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                            ),
                                    }),
                                    zod.object({
                                        kernel: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault
                                            )
                                            .describe('SVM kernel type (default: "rbf")'),
                                        nu: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault
                                            )
                                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                                        preprocessing: zod
                                            .union([
                                                zod.object({
                                                    diffs_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('ocsvm')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault
                                            )
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
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault
                                                        )
                                                        .describe(
                                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                        ),
                                                    lags_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault
                                                        )
                                                        .describe(
                                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                        ),
                                                    smooth_n: zod
                                                        .union([zod.number(), zod.null()])
                                                        .default(
                                                            alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault
                                                        )
                                                        .describe(
                                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                        ),
                                                }),
                                                zod.null(),
                                            ])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault
                                            )
                                            .describe('Preprocessing transforms applied before detection'),
                                        threshold: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault
                                            )
                                            .describe('Anomaly probability threshold (default: 0.9)'),
                                        type: zod
                                            .literal('pca')
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                            ),
                                        window: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault
                                            )
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
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneTwoPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneTwoThresholdDefault)
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('zscore').default(alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneTwoWindowDefault)
                            .describe('Rolling window size for calculating mean/std (default: 30)'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneThreePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneThreeThresholdDefault)
                            .describe(
                                'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                            ),
                        type: zod.literal('mad').default(alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneThreeWindowDefault)
                            .describe('Rolling window size for calculating median/MAD (default: 30)'),
                    }),
                    zod.object({
                        multiplier: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFourMultiplierDefault)
                            .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFourPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('iqr').default(alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFourWindowDefault)
                            .describe('Rolling window size for calculating quartiles (default: 30)'),
                    }),
                    zod.object({
                        lower_bound: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFiveLowerBoundDefault)
                            .describe('Lower bound - values below this are anomalies'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFivePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        type: zod.literal('threshold').default(alertsPartialUpdateBodyDetectorConfigOneFiveTypeDefault),
                        upper_bound: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneFiveUpperBoundDefault)
                            .describe('Upper bound - values above this are anomalies'),
                    }),
                    zod.object({
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSixPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSixThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ecod').default(alertsPartialUpdateBodyDetectorConfigOneSixTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSixWindowDefault)
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
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSevenPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSevenThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('copod').default(alertsPartialUpdateBodyDetectorConfigOneSevenTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneSevenWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_estimators: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightNEstimatorsDefault)
                            .describe('Number of trees in the forest (default: 100)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod
                            .literal('isolation_forest')
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneEightWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        method: zod
                            .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneNineMethodDefault)
                            .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneNineNNeighborsDefault)
                            .describe('Number of neighbors to consider (default: 5)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneNinePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneNineThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('knn').default(alertsPartialUpdateBodyDetectorConfigOneNineTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneNineWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_bins: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnezeroNBinsDefault)
                            .describe('Number of histogram bins (default: 10)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnezeroPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnezeroThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('hbos').default(alertsPartialUpdateBodyDetectorConfigOneOnezeroTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnezeroWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        n_neighbors: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOneoneNNeighborsDefault)
                            .describe('Number of neighbors for LOF (default: 20)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOneonePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOneoneThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('lof').default(alertsPartialUpdateBodyDetectorConfigOneOneoneTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOneoneWindowDefault)
                            .describe(
                                'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                            ),
                    }),
                    zod.object({
                        kernel: zod
                            .union([zod.string(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnetwoKernelDefault)
                            .describe('SVM kernel type (default: "rbf")'),
                        nu: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnetwoNuDefault)
                            .describe('Upper bound on training errors fraction (default: 0.1)'),
                        preprocessing: zod
                            .union([
                                zod.object({
                                    diffs_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnetwoPreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnetwoThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('ocsvm').default(alertsPartialUpdateBodyDetectorConfigOneOnetwoTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnetwoWindowDefault)
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
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault
                                        )
                                        .describe(
                                            'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                        ),
                                    lags_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault
                                        )
                                        .describe(
                                            'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                        ),
                                    smooth_n: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault
                                        )
                                        .describe(
                                            'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                        ),
                                }),
                                zod.null(),
                            ])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnethreePreprocessingDefault)
                            .describe('Preprocessing transforms applied before detection'),
                        threshold: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnethreeThresholdDefault)
                            .describe('Anomaly probability threshold (default: 0.9)'),
                        type: zod.literal('pca').default(alertsPartialUpdateBodyDetectorConfigOneOnethreeTypeDefault),
                        window: zod
                            .union([zod.number(), zod.null()])
                            .default(alertsPartialUpdateBodyDetectorConfigOneOnethreeWindowDefault)
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

export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneTwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreeThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneThreeWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourMultiplierDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneFourWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFiveLowerBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneFiveUpperBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneSixWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneSevenWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightNEstimatorsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneEightWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineMethodDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneNineWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroNBinsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneoneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoKernelDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoNuDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeWindowDefault = null
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
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault
                                    )
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .literal('zscore')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault)
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault
                                    )
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .literal('mad')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault)
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault
                                    )
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .literal('iqr')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault
                                    )
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault
                                    )
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .literal('threshold')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault
                                    )
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('ecod')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault)
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
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('copod')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault
                                    )
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('isolation_forest')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod
                                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightMethodDefault
                                    )
                                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault
                                    )
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('knn')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault)
                                    .describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('hbos')
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault
                                    )
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('lof')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod
                                    .union([zod.string(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault
                                    )
                                    .describe('SVM kernel type (default: "rbf")'),
                                nu: zod
                                    .union([zod.number(), zod.null()])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault)
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('ocsvm')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault
                                    )
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
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneDiffsNDefault
                                                )
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneLagsNDefault
                                                )
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingOneSmoothNDefault
                                                )
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDefault
                                    )
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .literal('pca')
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault
                                    )
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
                                .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneTwoThresholdDefault)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.literal('zscore').default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneTwoWindowDefault)
                    .describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneThreeThresholdDefault)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.literal('mad').default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneThreeWindowDefault)
                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFourMultiplierDefault)
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.literal('iqr').default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFourWindowDefault)
                    .describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFiveLowerBoundDefault)
                    .describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.literal('threshold').default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneFiveUpperBoundDefault)
                    .describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSixThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('ecod').default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSixWindowDefault)
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
                                .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSevenThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('copod').default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneSevenWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightNEstimatorsDefault)
                    .describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod
                    .literal('isolation_forest')
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod
                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineMethodDefault)
                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineNNeighborsDefault)
                    .describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('knn').default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroNBinsDefault)
                    .describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('hbos').default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneNNeighborsDefault)
                    .describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('lof').default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod
                    .union([zod.string(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoKernelDefault)
                    .describe('SVM kernel type (default: "rbf")'),
                nu: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoNuDefault)
                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingOneSmoothNDefault)
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('ocsvm').default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoWindowDefault)
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
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneDiffsNDefault)
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneLagsNDefault)
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingOneSmoothNDefault
                                )
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingDefault)
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnethreeThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.literal('pca').default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnethreeWindowDefault)
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
