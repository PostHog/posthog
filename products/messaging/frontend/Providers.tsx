import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { FunctionsTable } from './FunctionsTable'
import { MessagingTabs } from './MessagingTabs'
import { providersLogic } from './providersLogic'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { HogFunctionTemplateList } from 'scenes/pipeline/hogfunctions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'

export function Providers(): JSX.Element {
    const { providerId, templateId } = useValues(providersLogic)
    return providerId ? (
        <HogFunctionConfiguration id={providerId} templateId={templateId} />
    ) : (
        <>
            <MessagingTabs key="tabs" />
            <PageHeader caption="Configure e-mail, SMS and other messaging providers here" />
            <FunctionsTable type="email" />
            <div className="mt-4" />
            <h2>Add Provider</h2>
            <HogFunctionTemplateList defaultFilters={{}} type="email" />
            <div className="mt-2 text-muted">
                Note: to add a provider that's not in the list, select one that's similar and edit its source to point
                to the right API URLs
            </div>
        </>
    )
}
export const scene: SceneExport = {
    component: Providers,
    logic: providersLogic,
}
