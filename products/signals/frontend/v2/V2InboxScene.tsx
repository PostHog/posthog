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
import { ReportRow } from './components/ReportRow'
import { InboxDemoFilter, InboxDemoSort } from './types'
import { v2InboxLogic } from './v2InboxLogic'

export const scene: SceneExport = {
    component: V2InboxScene,
    logic: v2InboxLogic,
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

export function V2InboxScene(): JSX.Element {
    const { filter, sort, filteredReports, prModalTarget } = useValues(v2InboxLogic)
    const { setFilter, setSort, closePrModal, confirmPrModal } = useActions(v2InboxLogic)

    useKeyboardHotkeys(
        {
            // The modal's selects and buttons aren't inputs, so the shortcut would fire behind it
            f: {
                action: () => router.actions.push(urls.v2Focus()),
                disabled: prModalTarget !== null,
            },
        },
        [prModalTarget]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Inbox"
                description="Redesign preview with sample data"
                resourceType={{ type: 'inbox' }}
            />

            <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <div className="flex flex-wrap items-center gap-1">
                        {FILTER_OPTIONS.map((option) => (
                            <LemonButton
                                key={option.value}
                                size="small"
                                type="secondary"
                                active={filter === option.value}
                                onClick={() => setFilter(option.value)}
                                data-attr={`v2-filter-${option.value}`}
                            >
                                {option.label}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex-1" />
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.v2Focus()}
                        sideIcon={<KeyboardShortcut f />}
                        data-attr="v2-focus-mode"
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
                            'data-attr': `v2-sort-${option.value}`,
                        }))}
                    />
                </div>

                <div className="flex flex-col gap-2">
                    {filteredReports.length === 0 ? (
                        <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-secondary">
                            No reports match this filter. Pick another filter to see more.
                        </div>
                    ) : (
                        filteredReports.map((report) => <ReportRow key={report.id} report={report} />)
                    )}
                </div>
            </div>

            <CreatePrModal
                isOpen={prModalTarget !== null}
                flagKey={prModalTarget?.flagKey ?? ''}
                onClose={closePrModal}
                onConfirm={confirmPrModal}
            />
        </SceneContent>
    )
}

export default V2InboxScene
