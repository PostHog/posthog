import type { SentryMigrationCategoryEnumApi, SentryMigrationItemApi } from '../../../generated/api.schemas'
import type { ImportWizardStepperStep } from './ImportWizardStepper'

export enum ImportWizardStep {
    Source = 'source',
    Location = 'location',
    Token = 'token',
    Project = 'project',
    RateLimits = 'rate_limits',
    ErrorMessages = 'error_messages',
    Releases = 'releases',
    InboundFilters = 'inbound_filters',
    Review = 'review',
}

export interface ImportCategory {
    category: SentryMigrationCategoryEnumApi
    step: ImportWizardStep
    label: string
    title: string
    description: string
}

export const IMPORT_CATEGORIES: ImportCategory[] = [
    {
        category: 'rate_limit',
        step: ImportWizardStep.RateLimits,
        label: 'Rate limit',
        title: 'Rate limit',
        description: 'PostHog has one rate limit per project. Importing one replaces the current limit.',
    },
    {
        category: 'error_message',
        step: ImportWizardStep.ErrorMessages,
        label: 'Error messages',
        title: 'Error message filters',
        description: 'Each one becomes a manual suppression rule.',
    },
    {
        category: 'release',
        step: ImportWizardStep.Releases,
        label: 'Releases',
        title: 'Release filters',
        description: 'Each one becomes a manual suppression rule.',
    },
    {
        category: 'inbound_filter',
        step: ImportWizardStep.InboundFilters,
        label: 'Inbound filters',
        title: 'Inbound filters',
        description: 'Each one turns on the matching automatic suppression rule, which PostHog keeps up to date.',
    },
]

const SETUP_STEPS: ImportWizardStepperStep<ImportWizardStep>[] = [
    { key: ImportWizardStep.Source, label: 'Tool' },
    { key: ImportWizardStep.Location, label: 'URL' },
    { key: ImportWizardStep.Token, label: 'Token' },
    { key: ImportWizardStep.Project, label: 'Project' },
]

/** The setup steps, then one step per section the Sentry project has, then the review. */
export function wizardSteps(items: SentryMigrationItemApi[] | null): ImportWizardStepperStep<ImportWizardStep>[] {
    if (!items || items.length === 0) {
        return SETUP_STEPS
    }
    const sectionSteps = IMPORT_CATEGORIES.filter(({ category }) =>
        items.some((item) => item.category === category)
    ).map(({ step, label }) => ({ key: step, label }))
    return [...SETUP_STEPS, ...sectionSteps, { key: ImportWizardStep.Review, label: 'Review' }]
}
