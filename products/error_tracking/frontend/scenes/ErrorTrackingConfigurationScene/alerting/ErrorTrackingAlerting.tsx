import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={['error-tracking-issue-created', 'error-tracking-issue-reopened']}
        />
    )
}
