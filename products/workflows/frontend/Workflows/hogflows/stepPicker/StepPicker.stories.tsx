import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import _hogFunctionTemplatesDestinations from '~/mocks/fixtures/_hogFunctionTemplatesDestinations.json'
import { HogFunctionTemplateType } from '~/types'

import { DESTINATION_TEMPLATES } from './stepCatalogTestTemplates'
import { StepPicker } from './StepPicker'
import { StepPickerLogicProps, stepPickerLogic } from './stepPickerLogic'
import { stepPickerPreferencesLogic } from './stepPickerPreferencesLogic'
import { StepPickerView } from './stepPickerPresentation'

const TEMPLATES_PATH = '/api/projects/:team_id/hog_function_templates'

const FIXTURE_ICONS = new Map(
    (_hogFunctionTemplatesDestinations.results as unknown as HogFunctionTemplateType[]).map((template) => [
        template.id,
        template.icon_url,
    ])
)

const TEMPLATES: HogFunctionTemplateType[] = DESTINATION_TEMPLATES.map((template) => ({
    ...template,
    icon_url: FIXTURE_ICONS.get(template.id) ?? template.icon_url,
}))

const PICKER_PROPS: StepPickerLogicProps = { surface: 'tree', isRowScopedTrigger: false, onPick: () => {} }

const FAVORITE_STEP_IDS = ['template-posthog-create-task', 'template-slack', 'template-hubspot', 'step-delay']
const RECENT_STEP_IDS = ['template-email', 'step-conditional_branch', 'template-posthog-classify']

// Stories in one file share a browser, so favorites saved by one story would leak into the next
const withoutSavedPreferences: Decorator = (Story) => {
    Object.keys(localStorage)
        .filter((storageKey) => storageKey.includes('stepPickerPreferencesLogic'))
        .forEach((storageKey) => localStorage.removeItem(storageKey))
    return <Story />
}

type StoryProps = {
    narrow?: boolean
    search?: string
    providerId?: string
    view?: StepPickerView
    selectedStepId?: string
    favoriteStepIds?: string[]
    recentStepIds?: string[]
}

function StepPickerStory({
    narrow,
    search,
    providerId,
    view,
    selectedStepId,
    favoriteStepIds = [],
    recentStepIds = [],
}: StoryProps): JSX.Element {
    const { setSearch, openProvider, setView, selectStep } = useActions(stepPickerLogic(PICKER_PROPS))

    useEffect(() => {
        const preferences = stepPickerPreferencesLogic.findMounted()
        for (const stepId of favoriteStepIds) {
            if (preferences && !preferences.values.favoriteStepIds.includes(stepId)) {
                preferences.actions.toggleFavoriteStep(stepId)
            }
        }
        for (const stepId of [...recentStepIds].reverse()) {
            preferences?.actions.recordRecentStep(stepId)
        }
        if (view) {
            setView(view)
        }
        if (search) {
            setSearch(search)
        }
        if (providerId) {
            openProvider(providerId)
        }
        if (selectedStepId) {
            selectStep(selectedStepId)
        }
    }, [
        search,
        providerId,
        view,
        selectedStepId,
        favoriteStepIds,
        recentStepIds,
        setSearch,
        openProvider,
        setView,
        selectStep,
    ])

    return (
        // Pinned size, so the container queries resolve the same way on every run
        <div className={`h-[45rem] border bg-surface-primary ${narrow ? 'w-[40rem]' : 'w-[75rem]'}`}>
            <StepPicker {...PICKER_PROPS} />
        </div>
    )
}

const meta: Meta<typeof StepPickerStory> = {
    title: 'Products/Workflows/Editor/Step picker',
    component: StepPickerStory,
    parameters: {
        layout: 'padded',
        featureFlags: [
            FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION,
            FEATURE_FLAGS.WORKFLOW_RUN_SCOUT_ACTION,
            FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS,
        ],
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=workflow-step-picker-provider]',
            viewport: { width: 1300, height: 800 },
        },
    },
    decorators: [
        withoutSavedPreferences,
        mswDecorator({
            get: { [TEMPLATES_PATH]: { count: TEMPLATES.length, results: TEMPLATES } },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof StepPickerStory>

export const Wide: Story = {}

export const Narrow: Story = { args: { narrow: true } }

export const Search: Story = { args: { search: 'hub' } }

export const VendorOpened: Story = { args: { providerId: 'vendor:HubSpot' } }

export const Favorites: Story = {
    args: {
        view: 'favorites',
        favoriteStepIds: FAVORITE_STEP_IDS,
        selectedStepId: 'template-slack',
    },
}

export const FavoritesEmpty: Story = { args: { view: 'favorites' } }

export const RecentlyUsed: Story = { args: { view: 'recents', recentStepIds: RECENT_STEP_IDS } }

export const RecentlyUsedEmpty: Story = { args: { view: 'recents' } }

export const StepDetailNotFavorite: Story = { args: { view: 'highlights', selectedStepId: 'template-slack' } }

export const LoadingIntegrations: Story = {
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                [TEMPLATES_PATH]: () => new Promise(() => {}),
            },
        }),
    ],
}

export const IntegrationsFailed: Story = {
    decorators: [mswDecorator({ get: { [TEMPLATES_PATH]: () => [500, { detail: 'Server error' }] } })],
}
