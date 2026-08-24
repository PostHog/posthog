import { useActions, useMountedLogic, useValues } from 'kea'
import { JSX } from 'react'

import { IconCheckCircle, IconInfo, IconNotebook, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTabs, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import {
    INBOX_FLAT_LIST_TAB_KEYS,
    INBOX_FLAT_TAB_DESCRIPTION,
    INBOX_FLAT_TAB_LABEL,
    INBOX_FLAT_TAB_TAG,
    INBOX_STAFF_ONLY_FLAT_LIST_TAB_KEYS,
    InboxFlatListTabKey,
} from '../../types'
import { ReportCard } from '../cards/ReportCard'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxReportList } from '../InboxReportList'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'

/**
 * Count chip for a report view. Mounts that view's `reportListLogic` so its `count` (a cheap
 * `limit=1` request) is available for the chip before the view is ever opened. The active view
 * shares the same keyed instance, so no double-fetch.
 */
function ViewCount({ tabKey }: { tabKey: InboxFlatListTabKey }): JSX.Element {
    const logic = reportListLogic({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
    useMountedLogic(logic)
    const { count, countLoading } = useValues(logic)
    // Skeleton only while the request is genuinely in flight; on failure `count` stays null,
    // so fall back to the number (0) rather than a permanent skeleton.
    if (count === null && countLoading) {
        return <LemonSkeleton className="h-3 w-3 rounded" />
    }
    return <span className="text-xs text-muted tabular-nums">{count ?? 0}</span>
}

/** The view switcher: Needs a decision / Monitoring / Resolved, plus Not actionable for staff. */
function ReportsViewTabs(): JSX.Element {
    const { effectiveFlatListTab, isStaff } = useValues(inboxSceneLogic)
    const { setActiveFlatListTab } = useActions(inboxSceneLogic)

    const visibleKeys = INBOX_FLAT_LIST_TAB_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_FLAT_LIST_TAB_KEYS.includes(key)
    )

    return (
        <LemonTabs<InboxFlatListTabKey>
            activeKey={effectiveFlatListTab}
            onChange={setActiveFlatListTab}
            size="small"
            // Grows into whatever the controls beside it leave, and scrolls its bar past that. The
            // 16rem basis is what keeps it from being squeezed to nothing on a phone: below that the
            // row wraps and the controls drop under the tabs instead. The empty content slot is
            // hidden so the bar sits on the same baseline as the buttons.
            className="min-w-0 flex-1 basis-64 [&>.LemonTabs__content]:hidden"
            // The page tab bar above already draws the full-width divider; this switcher sits
            // inside the column as a plain row of tabs.
            barClassName="before:hidden mb-0"
            data-attr="inbox-report-views"
            tabs={visibleKeys.map((key) => ({
                key,
                label: (
                    <Tooltip title={INBOX_FLAT_TAB_DESCRIPTION[key]} placement="bottom">
                        <span className="flex items-center gap-1.5">
                            <span>{INBOX_FLAT_TAB_LABEL[key]}</span>
                            <ViewCount tabKey={key} />
                            {INBOX_FLAT_TAB_TAG[key] && (
                                <LemonTag type="completion" size="small">
                                    {INBOX_FLAT_TAB_TAG[key]}
                                </LemonTag>
                            )}
                        </span>
                    </Tooltip>
                ),
                content: <></>,
            }))}
        />
    )
}

type ReportsViewEmptyState =
    | { content: JSX.Element }
    | { icon: JSX.Element; title: string; description: string; extra?: JSX.Element }

function emptyStateFor(view: InboxFlatListTabKey, showWaitingForWork: boolean): ReportsViewEmptyState {
    switch (view) {
        case 'needs-decision':
            return {
                icon: <IconNotebook className="text-2xl" />,
                title: 'Nothing needs a decision',
                description:
                    'Reports land here when an agent finds something worth your judgment and no clean code change to draft.',
                extra: (
                    <SelfDrivingInstallingHint>
                        Reports will start arriving as soon as live data comes in.
                    </SelfDrivingInstallingHint>
                ),
            }
        case 'monitoring':
            return showWaitingForWork
                ? { content: <InboxWaitingForWork /> }
                : {
                      icon: <IconPullRequest className="text-2xl" />,
                      title: 'Nothing being monitored',
                      description:
                          'When an agent ships a code change, the pull request lands here for you to review and merge.',
                      extra: (
                          <SelfDrivingInstallingHint>
                              Pull requests will be opened as soon as live data comes in.
                          </SelfDrivingInstallingHint>
                      ),
                  }
        case 'resolved':
            return {
                icon: <IconCheckCircle className="text-2xl" />,
                title: 'Nothing resolved yet',
                description:
                    'Reports resolved by a merged pull request land here, along with reports you archived. You can restore an archived report at any time.',
            }
        case 'not-actionable':
            return {
                icon: <IconInfo className="text-2xl" />,
                title: 'Nothing judged not actionable',
                description:
                    'Reports the agent decided are not actionable land here, so the team can audit signal quality.',
            }
    }
}

/**
 * The Reports tab: a view switcher (Needs a decision / Monitoring / Resolved) with focus mode on the
 * same row, then the active view's filter bar (scope, search, sort, filters) and report list. Each view owns
 * its own filtered request, count, and pagination via the keyed `reportListLogic`; the list is
 * keyed on the view so its per-mount telemetry guards reset when the view changes.
 */
export function ReportsTab(): JSX.Element {
    const { effectiveFlatListTab } = useValues(inboxSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showWaitingForWork = featureFlags[FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE] === 'empty-state'
    const view = effectiveFlatListTab

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                <ReportsViewTabs />
                <LemonButton
                    type="primary"
                    size="small"
                    to={urls.inboxFocus()}
                    sideIcon={<KeyboardShortcut f />}
                    tooltip="Go through the reports that need a decision one at a time"
                    className="shrink-0"
                    data-attr="inbox-focus-mode"
                >
                    Focus mode
                </LemonButton>
            </div>
            <InboxReportList
                key={view}
                tabKey={view}
                listParams={INBOX_FLAT_TAB_LIST_PARAMS[view]}
                Card={ReportCard}
                emptyState={emptyStateFor(view, showWaitingForWork)}
            />
        </div>
    )
}
