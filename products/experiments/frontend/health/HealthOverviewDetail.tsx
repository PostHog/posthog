import { useValues } from 'kea'

import { IconInfo, IconWarning } from '@posthog/icons'

import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { type Noun, groupsModel } from '~/models/groupsModel'

import type { EvaluationRuntimeEnumApi, ExperimentHealthSetupApi } from '../generated/api.schemas'
import { HEALTH_CHECK_STATUS_DISPLAY } from './healthCheckStatusDisplay'
import type { HealthReading } from './healthCheckValues'
import { type HealthPanelCheck, countHealthChecks } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'
import { HealthPanelSection } from './HealthPanelSection'
import { HealthReadingList } from './HealthReadingList'

const RUNTIME_LABELS: Record<EvaluationRuntimeEnumApi, string> = {
    all: 'Client and server SDKs',
    client: 'Client SDKs only',
    server: 'Server SDKs only',
}

const MAX_LISTED_CONDITIONS = 3

function joinWithOr(items: string[]): string {
    return items.length <= 2 ? items.join(' or ') : `${items.slice(0, -1).join(', ')}, or ${items[items.length - 1]}`
}

function releaseConditionsText(
    conditions: ExperimentHealthSetupApi['release_conditions'],
    pluralOf: (groupTypeIndex: number | null) => string
): string {
    if (conditions.length === 0) {
        return 'None'
    }
    if (conditions.length > MAX_LISTED_CONDITIONS) {
        return `${conditions.length} condition sets`
    }
    const sets = conditions.map(({ rollout_percentage, property_count, aggregation_group_type_index }) => {
        const entities = pluralOf(aggregation_group_type_index)
        const matching = property_count > 0 ? ` matching ${pluralize(property_count, 'filter')}` : ''
        if (rollout_percentage >= 100) {
            return `all ${entities}${matching}`
        }
        const share = Math.round(rollout_percentage * 100) / 100
        return `${share}% of ${matching ? entities : `all ${entities}`}${matching}`
    })
    // Numbered as on the flag page, because the sets are the stored configuration, not the users they reach.
    return sets.length === 1
        ? capitalizeFirstLetter(sets[0])
        : sets.map((set, index) => `Set ${index + 1}: ${set}`).join(' · ')
}

function buildSetupReadings(
    setup: ExperimentHealthSetupApi,
    aggregationLabel: (groupTypeIndex: number) => Noun
): HealthReading[] {
    const pluralOf = (groupTypeIndex: number | null): string =>
        groupTypeIndex !== null ? aggregationLabel(groupTypeIndex).plural : 'users'
    const assignmentUnit = (groupTypeIndex: number | null): string =>
        groupTypeIndex !== null
            ? capitalizeFirstLetter(aggregationLabel(groupTypeIndex).singular)
            : setup.bucketing_identifier === 'device_id'
              ? 'Device (device ID)'
              : 'User (distinct ID)'
    const assignmentUnits = [
        ...new Set(
            setup.release_conditions.map(({ aggregation_group_type_index }) =>
                assignmentUnit(aggregation_group_type_index)
            )
        ),
    ]
    return [
        { label: 'Release conditions', text: releaseConditionsText(setup.release_conditions, pluralOf) },
        // The flag page describes early exit in these words.
        ...(setup.early_exit
            ? [{ label: 'Early exit', text: 'Stops evaluation at first matching condition set' }]
            : []),
        ...(assignmentUnits.length > 0 ? [{ label: 'Assigns variants by', text: joinWithOr(assignmentUnits) }] : []),
        { label: 'Evaluation runtime', text: RUNTIME_LABELS[setup.evaluation_runtime] },
        ...(setup.evaluation_contexts.length > 0
            ? [
                  {
                      label: 'Evaluation contexts',
                      text: `Only SDKs that send ${joinWithOr(setup.evaluation_contexts)}, or no context`,
                  },
              ]
            : []),
        {
            label: 'Persist flag across authentication steps',
            text: setup.ensure_experience_continuity ? 'On' : 'Off',
        },
    ]
}

export function HealthOverviewDetail({
    checks,
    findings,
    setup,
}: {
    checks: HealthPanelCheck[]
    findings: HealthPanelFinding[]
    setup: ExperimentHealthSetupApi | null
}): JSX.Element {
    const { aggregationLabel } = useValues(groupsModel)
    const setupReadings = setup ? buildSetupReadings(setup, aggregationLabel) : []
    const issues = healthIssues(findings)
    const issueIcon = (
        <IconWarning
            className={issues.some(({ severity }) => severity === 'critical') ? 'text-danger' : 'text-warning'}
        />
    )
    const noteCount = findings.length - issues.length
    const passedCount = countHealthChecks(checks, 'passed')
    const notApplicableCount = countHealthChecks(checks, 'not_applicable')
    const counts = [
        {
            key: 'issues',
            icon: issueIcon,
            count: issues.length,
            label: pluralize(issues.length, 'issue', undefined, false),
        },
        {
            key: 'notes',
            icon: <IconInfo className="text-secondary" />,
            count: noteCount,
            label: pluralize(noteCount, 'note', undefined, false),
        },
        { key: 'passed', icon: HEALTH_CHECK_STATUS_DISPLAY.passed.icon, count: passedCount, label: 'found no issue' },
        {
            key: 'not_checked',
            icon: HEALTH_CHECK_STATUS_DISPLAY.not_checked.icon,
            count: countHealthChecks(checks, 'not_checked'),
            label: "couldn't check",
        },
        {
            key: 'not_applicable',
            icon: HEALTH_CHECK_STATUS_DISPLAY.not_applicable.icon,
            count: notApplicableCount,
            label: notApplicableCount === 1 ? "doesn't apply" : "don't apply",
        },
    ].filter(({ count }) => count > 0)

    return (
        // pinned: `data-attr` value, so renaming it breaks autocapture insights
        <div className="flex flex-col gap-6" data-attr="experiment-health-summary-detail">
            <div className="flex flex-col gap-3">
                <h3 className="m-0 text-xl font-semibold">Overview</h3>
                {counts.length > 0 && (
                    <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0">
                        {counts.map(({ key, icon, count, label }) => (
                            <li key={key} className="flex items-center gap-1.5">
                                <span className="flex text-base">{icon}</span>
                                <span className="text-lg font-semibold tabular-nums">{count}</span>
                                <span className="text-secondary">{label}</span>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
            {setup && (
                <HealthPanelSection title="Setup">
                    <HealthReadingList readings={setupReadings} />
                </HealthPanelSection>
            )}
        </div>
    )
}
