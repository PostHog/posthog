import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

export function ConnectGitHubSource(): JSX.Element {
    return (
        <ProductIntroduction
            productName="Engineering analytics"
            productKey={ProductKey.ENGINEERING_ANALYTICS}
            thingName="GitHub source"
            titleOverride="Connect a GitHub source to get started"
            description="Engineering analytics reads pull requests and workflow runs from a GitHub data warehouse source. Connect one to see CI health, pull request throughput, and cost."
            isEmpty
            actionElementOverride={
                <LemonButton
                    type="primary"
                    to={urls.dataWarehouseSourceNew('Github')}
                    data-attr="engineering-analytics-connect-github"
                >
                    Connect GitHub source
                </LemonButton>
            }
        />
    )
}
