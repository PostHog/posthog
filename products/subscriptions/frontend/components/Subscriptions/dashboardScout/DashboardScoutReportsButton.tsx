import { useActions, useValues } from 'kea'

import { IconTelescope } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { DashboardScoutReportEntry } from './DashboardScoutReportEntry'
import { DashboardScoutReportLogicProps, dashboardScoutReportLogic } from './dashboardScoutReportLogic'

/** Opens the recent reports from a dashboard's scout. Renders nothing until the scout has filed one. */
export function DashboardScoutReportsButton(props: DashboardScoutReportLogicProps): JSX.Element | null {
    const logic = dashboardScoutReportLogic(props)
    const { reports, latestReportScout, reportsOpen } = useValues(logic)
    const { openReports, closeReports } = useActions(logic)

    if (!reports?.length) {
        return null
    }

    return (
        <>
            <LemonButton
                type="tertiary"
                size="small"
                icon={
                    <IconWithCount count={reports.length} showZero={false}>
                        <IconTelescope fontSize="16" />
                    </IconWithCount>
                }
                onClick={openReports}
                data-attr="dashboard-scout-reports-button"
            >
                Scout reports
            </LemonButton>
            <LemonModal
                isOpen={reportsOpen}
                onClose={closeReports}
                title="Scout reports"
                description="The latest reports from this dashboard's scout."
                width={640}
                footer={
                    <>
                        {latestReportScout ? (
                            <div className="flex-1">
                                <LemonButton
                                    type="tertiary"
                                    to={urls.inboxScout(latestReportScout.skill_name)}
                                    data-attr="dashboard-scout-all-reports-link"
                                >
                                    View all reports
                                </LemonButton>
                            </div>
                        ) : null}
                        <LemonButton type="secondary" onClick={closeReports}>
                            Close
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    {reports.map((report) => (
                        <DashboardScoutReportEntry key={report.id} report={report} />
                    ))}
                </div>
            </LemonModal>
        </>
    )
}
