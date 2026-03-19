/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
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
export const alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `threshold`
export const alertsCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsCreateBodyDetectorConfigOneFourTypeDefault = `threshold`

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
                                    .default(alertsCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound - values above this are anomalies'),
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
                type: zod.enum(['threshold']).default(alertsCreateBodyDetectorConfigOneFourTypeDefault),
                upper_bound: zod.number().nullish().describe('Upper bound - values above this are anomalies'),
            }),
        ])
        .describe('Detector configuration types')
        .nullish(),
    calculation_interval: zod
        .union([
            zod
                .enum(['hourly', 'daily', 'weekly', 'monthly'])
                .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod.boolean().nullish().describe('Skip alert evaluation on weekends (Saturday and Sunday).'),
})

export const AlertsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
export const alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `threshold`
export const alertsPartialUpdateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsPartialUpdateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsPartialUpdateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault = `threshold`

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
                                    .default(alertsPartialUpdateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .describe('Upper bound - values above this are anomalies'),
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
                type: zod.enum(['threshold']).default(alertsPartialUpdateBodyDetectorConfigOneFourTypeDefault),
                upper_bound: zod.number().nullish().describe('Upper bound - values above this are anomalies'),
            }),
        ])
        .describe('Detector configuration types')
        .nullish(),
    calculation_interval: zod
        .union([
            zod
                .enum(['hourly', 'daily', 'weekly', 'monthly'])
                .describe('* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often the alert is checked: hourly, daily, weekly, or monthly.\n\n* `hourly` - hourly\n* `daily` - daily\n* `weekly` - weekly\n* `monthly` - monthly'
        ),
    snoozed_until: zod
        .string()
        .nullish()
        .describe(
            "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze."
        ),
    skip_weekend: zod.boolean().nullish().describe('Skip alert evaluation on weekends (Saturday and Sunday).'),
})

export const AlertsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
