import { useActions } from 'kea'

import { IconArrowLeft, IconSidebarOpen } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { REPORT_AI_PANEL } from '~/layout/ai/aiPanelIds'
import { SidePanelTab } from '~/types'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, REPORT_AI_PANEL_ID } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'
import { ReportAiPanel } from './ReportAiPanel'

export function ReportChatMain({ report }: { report: SignalReport }): JSX.Element {
    const { hideMainChat, openSidePanel } = useActions(inboxTaskKickoffLogic)

    return (
        <div className="flex min-h-[70vh] min-w-0 flex-1 flex-col gap-3" data-attr="inbox-report-chat-main">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-primary pb-3">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={hideMainChat}
                    className="-ml-2"
                    data-attr="inbox-report-chat-main-back"
                >
                    Report summary
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconSidebarOpen />}
                    onClick={() => {
                        captureInboxReportAction({
                            report,
                            actionType: 'collapse_section',
                            surface: 'detail_pane',
                            extra: { section: 'main_chat' },
                        })
                        hideMainChat()
                        openSidePanel(SidePanelTab.Max, REPORT_AI_PANEL)
                    }}
                    data-attr="inbox-report-chat-main-pop-out"
                >
                    Move to side panel
                </LemonButton>
            </div>
            <ReportAiPanel panelId={REPORT_AI_PANEL_ID} />
        </div>
    )
}
