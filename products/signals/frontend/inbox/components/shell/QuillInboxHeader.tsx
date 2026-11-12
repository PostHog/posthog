import '../tabs/QuillInboxList.scss'

import { useValues } from 'kea'
import { router } from 'kea-router'

import { Heading, Tabs, TabsList, TabsTrigger, Text } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { urls } from 'scenes/urls'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { INBOX_TAB_DESCRIPTION, INBOX_TAB_KEYS, INBOX_TAB_LABEL, InboxTabKey } from '../../types'
import { ScoutsRosterActions } from '../config/scouts/ScoutsRosterActions'
import { InboxTriageButton } from './InboxTriageButton'
import { QuillInboxFilterMenu } from './QuillInboxFilterMenu'

export function QuillInboxHeader(): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { count: needsDecision } = useValues(reportListLogic(sectionListLogicProps('needs-decision')))
    const { count: monitoring } = useValues(reportListLogic(sectionListLogicProps('monitoring')))
    const openCount = needsDecision === null || monitoring === null ? null : needsDecision + monitoring
    const subtitle =
        activeTab !== 'reports' || openCount === null
            ? INBOX_TAB_DESCRIPTION[activeTab]
            : `${openCount} open ${openCount === 1 ? 'report' : 'reports'}`

    return (
        <div className="Today shrink-0">
            <header className="QuillInbox QuillInbox--header Today__page flex flex-col gap-5" data-quill>
                <div className="flex flex-col gap-0.5">
                    <Heading size="xl" render={<h1 className="m-0" />}>
                        Inbox
                    </Heading>
                    <Text size="sm" variant="muted" render={<p className="m-0" />}>
                        {subtitle}
                    </Text>
                </div>
                <div className="flex items-center justify-between gap-3 border-b border-border">
                    <Tabs
                        value={activeTab}
                        onValueChange={(key: InboxTabKey) => router.actions.push(urls.inbox(key))}
                        className="min-w-0 overflow-x-auto"
                        data-attr="inbox-tabs"
                    >
                        <TabsList variant="line" aria-label="Inbox pages">
                            {INBOX_TAB_KEYS.map((key) => (
                                <TabsTrigger key={key} value={key} data-attr={`inbox-tab-${key}`}>
                                    {INBOX_TAB_LABEL[key]}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                    </Tabs>
                    {activeTab === 'scouts' && (
                        <div className="flex shrink-0 items-center gap-1.5 pb-1.5">
                            <ScoutsRosterActions />
                        </div>
                    )}
                    {activeTab === 'reports' && (
                        <div className="flex shrink-0 items-center gap-1.5 pb-1.5">
                            <QuillInboxFilterMenu />
                            <InboxTriageButton compact={phoneLayout} />
                        </div>
                    )}
                </div>
            </header>
        </div>
    )
}
