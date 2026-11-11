import { Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { MetricsAlertLabelsField } from './MetricsAlertLabelsField'

export function MetricsAlertNotifyFields(): JSX.Element {
    return (
        <div className="space-y-3">
            <p className="text-sm m-0">
                Alert routes send this alert's notifications. A route sends when its conditions match the alert's
                labels. Set up routes and their destinations in{' '}
                <Link to={`${urls.platformAlerts()}?tab=routing`} target="_blank">
                    Alerts routing
                </Link>
                .
            </p>
            <LemonField
                name="labels"
                label="Labels"
                help="Names use letters, digits and underscores, such as team or severity."
            >
                <MetricsAlertLabelsField />
            </LemonField>
        </div>
    )
}
