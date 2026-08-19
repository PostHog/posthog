import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CreatePrModal } from './components/CreatePrModal'
import { InvestigationRow } from './components/InvestigationRow'
import { investigationsInboxLogic } from './investigationsInboxLogic'
import { InboxDemoFilter, InboxDemoSort } from './types'

export const scene: SceneExport = {
    component: InvestigationsInboxScene,
    logic: investigationsInboxLogic,
}

const FILTER_OPTIONS: { value: InboxDemoFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'attention', label: 'Needs attention' },
    { value: 'open', label: 'Open' },
    { value: 'monitoring', label: 'Monitoring' },
    { value: 'archived', label: 'Archived' },
]

const SORT_OPTIONS: { value: InboxDemoSort; label: string }[] = [
    { value: 'impact', label: 'Impact' },
    { value: 'recency', label: 'Recency' },
]

export function InvestigationsInboxScene(): JSX.Element {
    const { filter, sort, filteredInvestigations, prModalFlagKey } = useValues(investigationsInboxLogic)
    const { setFilter, setSort, closePrModal, confirmPrModal } = useActions(investigationsInboxLogic)

    useKeyboardHotkeys(
        {
            // The modal's selects and buttons aren't inputs, so the shortcut would fire behind it
            f: {
                action: () => router.actions.push(urls.investigationsDemoFocus()),
                disabled: prModalFlagKey !== null,
            },
        },
        [prModalFlagKey]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Inbox"
                description="Investigations redesign preview with sample data"
                resourceType={{ type: 'inbox' }}
            />

            <div className="flex w-full max-w-4xl flex-col gap-4">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <div className="flex flex-wrap items-center gap-1">
                        {FILTER_OPTIONS.map((option) => (
                            <LemonButton
                                key={option.value}
                                size="small"
                                type="secondary"
                                active={filter === option.value}
                                onClick={() => setFilter(option.value)}
                                data-attr={`investigations-demo-filter-${option.value}`}
                            >
                                {option.label}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex-1" />
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.investigationsDemoFocus()}
                        sideIcon={<KeyboardShortcut f />}
                        data-attr="investigations-demo-focus-mode"
                    >
                        Focus mode
                    </LemonButton>
                    <span className="text-xs text-tertiary">Sort by</span>
                    <LemonSegmentedButton
                        size="small"
                        value={sort}
                        onChange={setSort}
                        options={SORT_OPTIONS.map((option) => ({
                            ...option,
                            'data-attr': `investigations-demo-sort-${option.value}`,
                        }))}
                    />
                </div>

                <div className="flex flex-col gap-2">
                    {filteredInvestigations.length === 0 ? (
                        <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-secondary">
                            No investigations match this filter. Pick another filter to see more.
                        </div>
                    ) : (
                        filteredInvestigations.map((investigation) => (
                            <InvestigationRow key={investigation.id} investigation={investigation} />
                        ))
                    )}
                </div>
            </div>

            <CreatePrModal
                isOpen={prModalFlagKey !== null}
                flagKey={prModalFlagKey ?? ''}
                onClose={closePrModal}
                onConfirm={confirmPrModal}
            />
        </SceneContent>
    )
}

export default InvestigationsInboxScene
