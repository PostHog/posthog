import { isApprovalRequiredError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    FeatureFlagConfig,
    FeatureFlagFilters,
    FeatureFlagRulesV2Config,
    FeatureFlagRulesV2ReturnType,
    FeatureFlagRulesV2Rule,
    TeamPublicType,
    TeamType,
} from '~/types'

export type FeatureFlagConfigFormat = 'v1' | 'v2' | 'unsupported'

export const UNSUPPORTED_CONFIG_DISABLED_REASON =
    'This flag is stored in a configuration version this page cannot change.'
export const ARCHIVE_UNAVAILABLE_DISABLED_REASON = 'Archiving is not available for this flag yet.'
export const STALE_ROW_VERSION_RELOADED_MESSAGE = 'This flag changed elsewhere and has been reloaded.'

/** Mirrors the server's detector: no `version` or `1` is v1, `2` is v2, anything else is unsupported here. */
export function featureFlagConfigFormat(filters: FeatureFlagConfig | null | undefined): FeatureFlagConfigFormat {
    const version = filters?.version
    if (version === undefined || version === 1) {
        return 'v1'
    }
    if (version === 2) {
        return 'v2'
    }
    return 'unsupported'
}

export function isV1FeatureFlagConfig(filters: FeatureFlagConfig): filters is FeatureFlagFilters {
    return featureFlagConfigFormat(filters) === 'v1'
}

export function isRulesV2FeatureFlagConfig(filters: FeatureFlagConfig): filters is FeatureFlagRulesV2Config {
    return featureFlagConfigFormat(filters) === 'v2'
}

/** The server refuses `archived` on every config version but v1. */
export function canArchiveFeatureFlag(filters: FeatureFlagConfig | null | undefined): boolean {
    return featureFlagConfigFormat(filters) === 'v1'
}

/**
 * A write to a row in another config version must carry the row version. For a v1 row this returns
 * `{}`, so the write sends no version and the server applies it without a version check.
 */
export function rowVersionToken(
    flag: { filters?: FeatureFlagConfig | null; version?: number | null } | null | undefined
): { version?: number } {
    return !flag || featureFlagConfigFormat(flag.filters) === 'v1' || flag.version == null
        ? {}
        : { version: flag.version }
}

export function isStaleRowVersionError(token: { version?: number }, error: any): boolean {
    return token.version !== undefined && error?.status === 409 && !isApprovalRequiredError(error)
}

export function featureFlagConfigFormatLabel(filters: FeatureFlagConfig | null | undefined): string {
    const version = filters?.version
    switch (featureFlagConfigFormat(filters)) {
        case 'v1':
            return 'Config v1'
        case 'v2':
            return 'Rules v2'
        default:
            return typeof version === 'number' ? `Config v${version} (unsupported)` : 'Unsupported config'
    }
}

/** The rules v2 create contract rejects `evaluation_contexts`, so a project that requires them rejects every rules v2 create. */
export function rulesV2CreateDisabledReason(
    team: TeamPublicType | TeamType | null,
    enabledFeatures: FeatureFlagsSet
): string | null {
    return enabledFeatures[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] && team?.require_evaluation_contexts
        ? "This project requires evaluation contexts on new flags, and rules v2 flags can't set them yet."
        : null
}

export const RULES_V2_EDITABLE_RETURN_TYPES: FeatureFlagRulesV2ReturnType[] = ['boolean', 'string']

export function isRulesV2Value(value: unknown, returnType: FeatureFlagRulesV2ReturnType): boolean {
    switch (returnType) {
        case 'boolean':
            return typeof value === 'boolean'
        case 'string':
            return typeof value === 'string' && value !== ''
        default:
            return false
    }
}

function isRulesV2EditableRule(rule: FeatureFlagRulesV2Rule, returnType: FeatureFlagRulesV2ReturnType): boolean {
    switch (rule.rule_type) {
        case 'targeted_release':
        case 'percentage_rollout':
            return isRulesV2Value(rule.value, returnType)
        case 'experiment':
            // A linked experiment and a shared holdout are managed with their experiment, not here.
            return (
                rule.experiment_id === null &&
                (rule.holdout == null || rule.holdout.id === null) &&
                rule.variants.every((variant) => isRulesV2Value(variant.value, returnType))
            )
        default:
            return false
    }
}

/**
 * Whether the rules v2 editor is on and can edit this document: a return type it authors, person assignment, and
 * rules it can show. Anything else stays read-only, so a save never rewrites what the editor cannot represent.
 */
export function isRulesV2EditableConfig(filters: FeatureFlagConfig, enabledFeatures: FeatureFlagsSet): boolean {
    return (
        !!enabledFeatures[FEATURE_FLAGS.FEATURE_FLAG_RULES_V2_EDITOR] &&
        isRulesV2FeatureFlagConfig(filters) &&
        RULES_V2_EDITABLE_RETURN_TYPES.includes(filters.return_type) &&
        filters.aggregation_group_type_index == null &&
        filters.rules.every((rule) => isRulesV2EditableRule(rule, filters.return_type))
    )
}
