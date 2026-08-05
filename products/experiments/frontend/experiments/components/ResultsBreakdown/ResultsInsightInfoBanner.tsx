import { LemonBanner, Link } from '@posthog/lemon-ui'

import type { ResultBreakdownRenderProps } from './types'

type SafeResultsInsightInfoBanner = {
    [K in keyof Pick<ResultBreakdownRenderProps, 'exposureDifference'>]: NonNullable<ResultBreakdownRenderProps[K]>
}

export const ResultsInsightInfoBanner = ({ exposureDifference }: SafeResultsInsightInfoBanner): JSX.Element | null => {
    if (exposureDifference === 0) {
        return null
    }

    return (
        <LemonBanner type="info" className="mb-4">
            <div className="items-center inline-flex flex-wrap">
                <span>
                    Insight results may be slightly different from exposure results due to a difference in data
                    processing methods. We're actively working on fixing this.&nbsp;
                    <Link
                        to="https://posthog.com/docs/experiments/common-questions"
                        className="font-semibold text-primary hover:text-primary-dark"
                    >
                        Learn more in our docs
                    </Link>
                    .
                </span>
            </div>
        </LemonBanner>
    )
}
