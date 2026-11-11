import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { CIExplorerDrawerTab, ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerContext } from './CIExplorerContext'
import { CIExplorerJobDetails } from './CIExplorerJobDetails'

const TABS: { key: CIExplorerDrawerTab; label: string }[] = [
    { key: 'details', label: 'Details' },
    { key: 'context', label: 'Context' },
]

/**
 * The one drawer of the canvas. Closed, it is two buttons. Open, it shows what the selection is (Details) or how
 * it compares with recent runs (Context). The choice is remembered.
 */
export function CIExplorerDrawer({ maxHeight }: { maxHeight: number }): JSX.Element {
    const { drawerOpen, drawerTab, focusedJob } = useValues(ciExplorerLogic)
    const { openDrawer, closeDrawer } = useActions(ciExplorerLogic)

    if (!drawerOpen) {
        return (
            <div className="flex gap-1">
                {TABS.map((tab) => (
                    <LemonButton
                        key={tab.key}
                        type="secondary"
                        size="small"
                        onClick={() => openDrawer(tab.key)}
                        aria-expanded={false}
                        data-attr={`ci-explorer-drawer-open-${tab.key}`}
                    >
                        {tab.label}
                    </LemonButton>
                ))}
            </div>
        )
    }
    return (
        <aside
            className="flex w-80 max-w-[calc(100vw-4rem)] flex-col overflow-hidden rounded-lg border border-primary bg-surface-primary shadow-md"
            aria-label={drawerTab === 'context' ? 'Timing context' : 'Job details'}
            // The height follows the canvas, which only the canvas knows.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ maxHeight }}
        >
            <div className="flex items-center justify-between gap-2 border-b border-primary pl-3 pr-2">
                <LemonTabs
                    activeKey={drawerTab}
                    onChange={openDrawer}
                    tabs={TABS}
                    size="small"
                    barClassName="mb-0"
                    data-attr="ci-explorer-drawer-tabs"
                />
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    aria-label="Close"
                    onClick={closeDrawer}
                    data-attr="ci-explorer-drawer-close"
                />
            </div>
            <div className="flex min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain p-3">
                {drawerTab === 'context' ? (
                    <CIExplorerContext />
                ) : focusedJob ? (
                    <CIExplorerJobDetails job={focusedJob.job} run={focusedJob.run} />
                ) : (
                    <p className="m-0 text-xs text-secondary">Select a job</p>
                )}
            </div>
        </aside>
    )
}
