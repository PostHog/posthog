import { ReactNode } from 'react'

import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** The closed detail lines at the end of a stage. Each line opens in place. */
export function ReportStageDetails({ children }: { children?: ReactNode }): JSX.Element | null {
    if (!children) {
        return null
    }
    return (
        <section className="flex flex-col gap-1.5 empty:hidden" aria-label="Details">
            <ReportStageSectionTitle>Details</ReportStageSectionTitle>
            <div className="-mx-2 flex flex-col">{children}</div>
        </section>
    )
}
