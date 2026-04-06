/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List experiments for the current project. Supports filtering by status and archival state.
 */
export const ExperimentsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsCreateBodyNameMax = 400

export const experimentsCreateBodyDescriptionMax = 400

export const experimentsCreateBodyParametersFeatureFlagVariantsItemRolloutPercentageMin = 0
export const experimentsCreateBodyParametersFeatureFlagVariantsItemRolloutPercentageMax = 100

export const experimentsCreateBodyArchivedDefault = false

export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsCreateBodyNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsCreateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        feature_flag_key: zod
            .string()
            .describe("Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only."),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .object({
                feature_flag_variants: zod
                    .array(
                        zod.object({
                            key: zod.string().describe("Variant key (e.g., 'control', 'variant_a', 'new_design')."),
                            name: zod.string().optional().describe('Human-readable variant name.'),
                            rollout_percentage: zod
                                .number()
                                .min(experimentsCreateBodyParametersFeatureFlagVariantsItemRolloutPercentageMin)
                                .max(experimentsCreateBodyParametersFeatureFlagVariantsItemRolloutPercentageMax)
                                .describe('Percentage of users to show this variant.'),
                        })
                    )
                    .optional()
                    .describe('Experiment variants. If not specified, defaults to 50/50 control/test split.'),
                minimum_detectable_effect: zod
                    .number()
                    .optional()
                    .describe(
                        'Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30%% for most experiments.'
                    ),
            })
            .nullish()
            .describe(
                'Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.'
            ),
        secondary_metrics: zod.unknown().nullish(),
        saved_metrics_ids: zod
            .array(zod.record(zod.string(), zod.unknown()))
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsCreateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.literal(null)])
            .nullish()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .object({
                filterTestAccounts: zod.boolean().optional().describe('Whether to filter out internal test accounts.'),
                exposure_config: zod
                    .object({
                        kind: zod.enum(['ExperimentEventExposureConfig']).optional(),
                        event: zod.string().optional().describe('Custom exposure event name.'),
                    })
                    .optional()
                    .describe('Custom exposure event configuration.'),
            })
            .nullish()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .array(
                zod
                    .object({
                        kind: zod.enum(['ExperimentMetric']).describe("Must be 'ExperimentMetric'."),
                        metric_type: zod
                            .enum(['mean', 'funnel', 'ratio', 'retention'])
                            .describe('Type of metric measurement.'),
                        name: zod.string().optional().describe('Human-readable metric name.'),
                        uuid: zod
                            .string()
                            .optional()
                            .describe('Unique identifier for the metric. Auto-generated if not provided.'),
                        source: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional().describe("Event name, e.g. '$pageview'."),
                            })
                            .optional()
                            .describe("For mean metrics: EventsNode with 'kind' and 'event' fields."),
                        series: zod
                            .array(
                                zod.object({
                                    kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                    event: zod.string().optional(),
                                })
                            )
                            .optional()
                            .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                        numerator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the numerator EventsNode.'),
                        denominator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the denominator EventsNode.'),
                        goal: zod
                            .enum(['increase', 'decrease'])
                            .optional()
                            .describe('Whether higher or lower values indicate success.'),
                        conversion_window: zod.number().optional().describe('Conversion window duration.'),
                    })
                    .describe(
                        "Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease')."
                    )
            )
            .nullish()
            .describe(
                'Primary experiment metrics array. Each metric defines what to measure (e.g., mean, funnel, ratio).'
            ),
        metrics_secondary: zod
            .array(
                zod
                    .object({
                        kind: zod.enum(['ExperimentMetric']).describe("Must be 'ExperimentMetric'."),
                        metric_type: zod
                            .enum(['mean', 'funnel', 'ratio', 'retention'])
                            .describe('Type of metric measurement.'),
                        name: zod.string().optional().describe('Human-readable metric name.'),
                        uuid: zod
                            .string()
                            .optional()
                            .describe('Unique identifier for the metric. Auto-generated if not provided.'),
                        source: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional().describe("Event name, e.g. '$pageview'."),
                            })
                            .optional()
                            .describe("For mean metrics: EventsNode with 'kind' and 'event' fields."),
                        series: zod
                            .array(
                                zod.object({
                                    kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                    event: zod.string().optional(),
                                })
                            )
                            .optional()
                            .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                        numerator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the numerator EventsNode.'),
                        denominator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the denominator EventsNode.'),
                        goal: zod
                            .enum(['increase', 'decrease'])
                            .optional()
                            .describe('Whether higher or lower values indicate success.'),
                        conversion_window: zod.number().optional().describe('Conversion window duration.'),
                    })
                    .describe(
                        "Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease')."
                    )
            )
            .nullish()
            .describe('Secondary experiment metrics array for additional measurements.'),
        stats_config: zod.unknown().nullish(),
        scheduling_config: zod.unknown().nullish(),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().nullish(),
        secondary_metrics_ordered_uuids: zod.unknown().nullish(),
        exposure_preaggregation_enabled: zod.boolean().optional(),
        only_count_matured_users: zod.boolean().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
 */
export const ExperimentsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const ExperimentsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsPartialUpdateBodyNameMax = 400

export const experimentsPartialUpdateBodyDescriptionMax = 400

export const experimentsPartialUpdateBodyParametersFeatureFlagVariantsItemRolloutPercentageMin = 0
export const experimentsPartialUpdateBodyParametersFeatureFlagVariantsItemRolloutPercentageMax = 100

export const experimentsPartialUpdateBodyArchivedDefault = false

export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsPartialUpdateBodyNameMax).optional().describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        feature_flag_key: zod
            .string()
            .optional()
            .describe("Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only."),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .object({
                feature_flag_variants: zod
                    .array(
                        zod.object({
                            key: zod.string().describe("Variant key (e.g., 'control', 'variant_a', 'new_design')."),
                            name: zod.string().optional().describe('Human-readable variant name.'),
                            rollout_percentage: zod
                                .number()
                                .min(experimentsPartialUpdateBodyParametersFeatureFlagVariantsItemRolloutPercentageMin)
                                .max(experimentsPartialUpdateBodyParametersFeatureFlagVariantsItemRolloutPercentageMax)
                                .describe('Percentage of users to show this variant.'),
                        })
                    )
                    .optional()
                    .describe('Experiment variants. If not specified, defaults to 50/50 control/test split.'),
                minimum_detectable_effect: zod
                    .number()
                    .optional()
                    .describe(
                        'Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30%% for most experiments.'
                    ),
            })
            .nullish()
            .describe(
                'Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.'
            ),
        secondary_metrics: zod.unknown().nullish(),
        saved_metrics_ids: zod
            .array(zod.record(zod.string(), zod.unknown()))
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsPartialUpdateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.literal(null)])
            .nullish()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .object({
                filterTestAccounts: zod.boolean().optional().describe('Whether to filter out internal test accounts.'),
                exposure_config: zod
                    .object({
                        kind: zod.enum(['ExperimentEventExposureConfig']).optional(),
                        event: zod.string().optional().describe('Custom exposure event name.'),
                    })
                    .optional()
                    .describe('Custom exposure event configuration.'),
            })
            .nullish()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .array(
                zod
                    .object({
                        kind: zod.enum(['ExperimentMetric']).describe("Must be 'ExperimentMetric'."),
                        metric_type: zod
                            .enum(['mean', 'funnel', 'ratio', 'retention'])
                            .describe('Type of metric measurement.'),
                        name: zod.string().optional().describe('Human-readable metric name.'),
                        uuid: zod
                            .string()
                            .optional()
                            .describe('Unique identifier for the metric. Auto-generated if not provided.'),
                        source: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional().describe("Event name, e.g. '$pageview'."),
                            })
                            .optional()
                            .describe("For mean metrics: EventsNode with 'kind' and 'event' fields."),
                        series: zod
                            .array(
                                zod.object({
                                    kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                    event: zod.string().optional(),
                                })
                            )
                            .optional()
                            .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                        numerator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the numerator EventsNode.'),
                        denominator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the denominator EventsNode.'),
                        goal: zod
                            .enum(['increase', 'decrease'])
                            .optional()
                            .describe('Whether higher or lower values indicate success.'),
                        conversion_window: zod.number().optional().describe('Conversion window duration.'),
                    })
                    .describe(
                        "Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease')."
                    )
            )
            .nullish()
            .describe(
                'Primary experiment metrics array. Each metric defines what to measure (e.g., mean, funnel, ratio).'
            ),
        metrics_secondary: zod
            .array(
                zod
                    .object({
                        kind: zod.enum(['ExperimentMetric']).describe("Must be 'ExperimentMetric'."),
                        metric_type: zod
                            .enum(['mean', 'funnel', 'ratio', 'retention'])
                            .describe('Type of metric measurement.'),
                        name: zod.string().optional().describe('Human-readable metric name.'),
                        uuid: zod
                            .string()
                            .optional()
                            .describe('Unique identifier for the metric. Auto-generated if not provided.'),
                        source: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional().describe("Event name, e.g. '$pageview'."),
                            })
                            .optional()
                            .describe("For mean metrics: EventsNode with 'kind' and 'event' fields."),
                        series: zod
                            .array(
                                zod.object({
                                    kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                    event: zod.string().optional(),
                                })
                            )
                            .optional()
                            .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                        numerator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the numerator EventsNode.'),
                        denominator: zod
                            .object({
                                kind: zod.enum(['EventsNode', 'ActionsNode']).optional(),
                                event: zod.string().optional(),
                            })
                            .optional()
                            .describe('For ratio metrics: the denominator EventsNode.'),
                        goal: zod
                            .enum(['increase', 'decrease'])
                            .optional()
                            .describe('Whether higher or lower values indicate success.'),
                        conversion_window: zod.number().optional().describe('Conversion window duration.'),
                    })
                    .describe(
                        "Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease')."
                    )
            )
            .nullish()
            .describe('Secondary experiment metrics array for additional measurements.'),
        stats_config: zod.unknown().nullish(),
        scheduling_config: zod.unknown().nullish(),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().nullish(),
        secondary_metrics_ordered_uuids: zod.unknown().nullish(),
        exposure_preaggregation_enabled: zod.boolean().optional(),
        only_count_matured_users: zod.boolean().optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ExperimentsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Archive an ended experiment.

Hides the experiment from the default list view. The experiment can be
restored at any time by updating archived=false. Returns 400 if the
experiment is already archived or has not ended yet.
 */
export const ExperimentsArchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * End a running experiment without shipping a variant.

Sets end_date to now and marks the experiment as stopped. The feature
flag is NOT modified — users continue to see their assigned variants
and exposure events ($feature_flag_called) continue to be recorded.
However, only data up to end_date is included in experiment results.

Use this when:

- You want to freeze the results window without changing which variant
  users see.
- A variant was already shipped manually via the feature flag UI and
  the experiment just needs to be marked complete.

The end_date can be adjusted after ending via PATCH if it needs to be
backdated (e.g. to match when the flag was actually paused).

Other options:
- Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
- Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

Returns 400 if the experiment is not running.
 */
export const ExperimentsEndCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsEndCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
})

/**
 * Launch a draft experiment.

Validates the experiment is in draft state, activates its linked feature flag,
sets start_date to the current server time, and transitions the experiment to running.
Returns 400 if the experiment has already been launched or if the feature flag
configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
 */
export const ExperimentsLaunchCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Pause a running experiment.

Deactivates the linked feature flag so it is no longer returned by the
/decide endpoint. Users fall back to the application default (typically
the control experience), and no new exposure events are recorded (i.e.
$feature_flag_called is not fired).
Returns 400 if the experiment is not running or is already paused.
 */
export const ExperimentsPauseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Reset an experiment back to draft state.

Clears start/end dates, conclusion, and archived flag. The feature
flag is left unchanged — users continue to see their assigned variants.

Previously collected events still exist but won't be included in
results unless the start date is manually adjusted after re-launch.

Returns 400 if the experiment is already in draft state.
 */
export const ExperimentsResetCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Resume a paused experiment.

Reactivates the linked feature flag so it is returned by /decide again.
Users are re-bucketed deterministically into the same variants they had
before the pause, and exposure tracking resumes.
Returns 400 if the experiment is not running or is not paused.
 */
export const ExperimentsResumeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Ship a variant to 100% of users and (optionally) end the experiment.

Rewrites the feature flag so that the selected variant is served to everyone.
Existing release conditions (flag groups) are preserved so the change can be
rolled back by deleting the auto-added release condition in the feature flag UI.

Can be called on both running and stopped experiments. If the experiment is
still running, it will also be ended (end_date set and status marked as stopped).
If the experiment has already ended, only the flag is rewritten - this supports
the "end first, ship later" workflow.

If an approval policy requires review before changes on the flag take effect,
the API returns 409 with a change_request_id. The experiment is NOT ended until
the change request is approved and the user retries.

Returns 400 if the experiment is in draft state, the variant_key is not found
on the flag, or the experiment has no linked feature flag.
 */
export const ExperimentsShipVariantCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsShipVariantCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
    variant_key: zod.string().describe('The key of the variant to ship to 100% of users.'),
})
