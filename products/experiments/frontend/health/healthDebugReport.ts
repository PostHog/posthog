import type { ExperimentWarning } from 'scenes/experiments/experimentLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { getExperimentStatus } from '../experimentStatus'
import type { ExperimentHealthApi, ExperimentHealthFindingApi } from '../generated/api.schemas'
import { FLAG_STATE_FINDING_CODES, experimentWarningFromHealth } from './experimentHealthFindingEvents'
import { getTotalExposures } from './exposureHealth'
import { type HealthPanelFinding, ZERO_EXPOSURES_GRACE_HOURS } from './healthPanelFindings'

export type HealthDebugSource = 'server' | 'browser rules' | 'exposure answer'

export interface HealthDebugCheck {
    check: string
    source: HealthDebugSource
    result: string
    /** The inputs behind the result, or why the check gave none. */
    note: string | null
    /** True when the browser's rules and the server's check disagree. */
    differs: boolean
}

export interface HealthDebugInput {
    health: ExperimentHealthApi | null | undefined
    panelFindings: HealthPanelFinding[] | null
    browserWarning: ExperimentWarning | null
    browserNoMetricsWarning: boolean
    pageMetricCounts: { primary: number; secondary: number }
    isExperimentDraft: boolean
    hoursSinceStart: number | null
    exposures: ExperimentExposureQueryResponse | null | undefined
    exposuresLoading: boolean
    multipleVariantHandling: 'exclude' | 'first_seen'
}

const NO_FINDING = 'no finding'
const NOT_SENT = 'not sent'

export function describeServerHealth(health: ExperimentHealthApi | null | undefined): string {
    if (health === null) {
        return 'null: the experiment-health-findings flag is off for this user'
    }
    if (health === undefined) {
        return 'missing: a flag save outside the experiment API dropped the findings, so reload the page'
    }
    return `${health.findings.length} findings`
}

export function describePanel(panelFindings: HealthPanelFinding[] | null): string {
    if (panelFindings === null) {
        return 'hidden: no server health, so the page shows its separate warnings'
    }
    if (panelFindings.length === 0) {
        return 'hidden: no findings'
    }
    return `shows ${panelFindings.length} findings`
}

function warningLabel(warning: ExperimentWarning | null): string {
    if (!warning) {
        return NO_FINDING
    }
    return warning.variantKey ? `${warning.key} (${warning.variantKey})` : warning.key
}

function serverResult(
    health: ExperimentHealthApi | null | undefined,
    matches: (code: ExperimentHealthFindingApi['code']) => boolean
): string {
    if (!health) {
        return NOT_SENT
    }
    const finding = health.findings.find((candidate) => matches(candidate.code))
    if (!finding) {
        return NO_FINDING
    }
    const variantKey = finding.evidence.variant_key
    return [finding.code, finding.subcode, typeof variantKey === 'string' ? `(${variantKey})` : null]
        .filter(Boolean)
        .join(' · ')
}

function flagStateChecks(input: HealthDebugInput): HealthDebugCheck[] {
    const serverWarning = input.health ? experimentWarningFromHealth(input.health) : null
    // A subcode the page does not know maps to no warning, so it can match a browser that finds none.
    // The raw finding still counts as a difference then.
    const hasUnmappedServerFinding =
        !serverWarning && !!input.health?.findings.some((finding) => FLAG_STATE_FINDING_CODES.has(finding.code))
    const differs =
        !!input.health &&
        (hasUnmappedServerFinding || warningLabel(serverWarning) !== warningLabel(input.browserWarning))
    return [
        {
            check: 'flag_state',
            source: 'server',
            result: serverResult(input.health, (code) => FLAG_STATE_FINDING_CODES.has(code)),
            note: null,
            differs: false,
        },
        {
            check: 'flag_state',
            source: 'browser rules',
            result: warningLabel(input.browserWarning),
            note: differs ? "Differs from the server's finding. The page shows the server's." : null,
            differs,
        },
    ]
}

function noMetricChecks(input: HealthDebugInput): HealthDebugCheck[] {
    const { primary, secondary } = input.pageMetricCounts
    const serverFires = !!input.health?.findings.some((finding) => finding.code === 'no_metric')
    const differs = !!input.health && input.browserNoMetricsWarning !== serverFires
    return [
        {
            check: 'no_metric',
            source: 'server',
            result: serverResult(input.health, (code) => code === 'no_metric'),
            note: null,
            differs: false,
        },
        {
            check: 'no_metric',
            source: 'browser rules',
            result: input.browserNoMetricsWarning ? 'no_metric' : NO_FINDING,
            note: `The page lists ${primary} primary and ${secondary} secondary metrics.${
                differs ? " Differs from the server's finding. The page shows the server's." : ''
            }`,
            differs,
        },
    ]
}

function exposureChecks(input: HealthDebugInput): HealthDebugCheck[] {
    const { exposures } = input
    const panelCodes = new Set(input.panelFindings?.map((finding) => finding.code))
    const serverCodes = new Set<string>(input.health?.findings.map((finding) => finding.code))
    const skipped = input.isExperimentDraft
        ? 'skipped: the experiment is a draft'
        : !exposures
          ? input.exposuresLoading
              ? 'skipped: the exposures are loading'
              : 'skipped: no exposure answer'
          : null

    const result = (code: HealthPanelFinding['code']): string => {
        if (skipped) {
            return skipped
        }
        if (serverCodes.has(code)) {
            return 'not added: the server sent this code'
        }
        return panelCodes.has(code) ? code : NO_FINDING
    }

    const total = getTotalExposures(exposures)
    const multiple = Number(exposures?.total_exposures?.[EXPERIMENT_VARIANT_MULTIPLE] || 0)
    const pValue = exposures?.sample_ratio_mismatch?.p_value
    return [
        {
            check: 'zero_exposures',
            source: 'exposure answer',
            result: result('zero_exposures'),
            note: exposures
                ? `${total} users exposed. ${
                      input.hoursSinceStart === null
                          ? 'Not launched.'
                          : `Started ${Math.floor(input.hoursSinceStart)} hours ago. The finding waits ${ZERO_EXPOSURES_GRACE_HOURS} hours.`
                  }`
                : null,
            differs: false,
        },
        {
            check: 'srm',
            source: 'exposure answer',
            result: result('srm'),
            note: exposures
                ? pValue != null
                    ? `p = ${pValue.toPrecision(3)}. The finding needs p < 0.001.`
                    : 'The exposure answer has no sample ratio test.'
                : null,
            differs: false,
        },
        {
            check: 'bias_risk_multiple_excluded',
            source: 'exposure answer',
            result: result('bias_risk_multiple_excluded'),
            note: exposures
                ? `${exposures.bias_risk ? `bias_risk ${exposures.bias_risk.multiple_variant_percentage.toFixed(2)}%` : 'No bias_risk in the answer'}. $multiple: ${multiple} of ${total} users. Handling: ${input.multipleVariantHandling}.`
                : null,
            differs: false,
        },
    ]
}

/** One row per check and source, so a reader can see why the health panel shows what it shows. */
export function buildHealthDebugChecks(input: HealthDebugInput): HealthDebugCheck[] {
    return [
        ...flagStateChecks(input),
        ...noMetricChecks(input),
        {
            check: 'bias_risk_multiple_excluded',
            source: 'server',
            result: serverResult(input.health, (code) => code === 'bias_risk_multiple_excluded'),
            note: null,
            differs: false,
        },
        ...exposureChecks(input),
    ]
}

export interface HealthDebugFact {
    label: string
    value: string
}

function percentage(value: unknown): string {
    return typeof value === 'number' ? `${value}%` : 'unset'
}

/** The experiment and flag state that the server's checks read, as the browser holds it. */
export function buildHealthDebugFacts(
    experiment: Experiment,
    pageMetricCounts: HealthDebugInput['pageMetricCounts']
): HealthDebugFact[] {
    const flag = experiment.feature_flag
    const groups = flag?.filters?.groups ?? []
    const variants = flag?.filters?.multivariate?.variants ?? []
    const sharedMetricTypes = (experiment.saved_metrics ?? []).map(
        (link: { metadata?: { type?: string } }) => link.metadata?.type ?? 'none'
    )
    const countType = (type: string): number => sharedMetricTypes.filter((linkType) => linkType === type).length

    return [
        { label: 'Status', value: getExperimentStatus(experiment) },
        { label: 'Start date', value: experiment.start_date ?? 'none' },
        { label: 'End date', value: experiment.end_date ?? 'none' },
        { label: 'Archived', value: String(!!experiment.archived) },
        {
            label: 'Feature flag',
            value: flag ? `${flag.key}, active: ${flag.active}, deleted: ${!!flag.deleted}` : 'none',
        },
        {
            label: 'Release groups',
            value: groups.length
                ? groups
                      .map((group) => {
                          const properties = Array.isArray(group.properties) ? group.properties.length : 0
                          return `${percentage(group.rollout_percentage)} with ${properties} properties`
                      })
                      .join('; ')
                : 'none',
        },
        {
            label: 'Variants',
            value: variants.length
                ? variants.map((variant) => `${variant.key} ${percentage(variant.rollout_percentage)}`).join(', ')
                : 'none',
        },
        {
            label: 'Single-use metrics',
            value: `${experiment.metrics?.length ?? 0} primary, ${experiment.metrics_secondary?.length ?? 0} secondary`,
        },
        {
            label: 'Shared metric links',
            value: `${countType('primary')} primary, ${countType('secondary')} secondary, ${countType('none')} without a type`,
        },
        {
            label: 'Metrics the page lists',
            value: `${pageMetricCounts.primary} primary, ${pageMetricCounts.secondary} secondary`,
        },
    ]
}
