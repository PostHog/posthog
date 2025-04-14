import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { SceneExport } from 'scenes/sceneTypes'

import { libraryTemplateLogic } from './libraryTemplateLogic'

export function LibraryTemplate(): JSX.Element {
    return (
        <HogFunctionConfiguration
            id={null}
            templateId="template-new-campaign"
            displayOptions={{
                showPersonsCount: false,
                showFilters: false,
                showTesting: false,
                showEnabled: false,
                canEditSource: false,
                showExpectedVolume: false,
            }}
        />
    )
}

export const scene: SceneExport = {
    component: LibraryTemplate,
    logic: libraryTemplateLogic,
    paramsToProps: ({ params: { id } }): (typeof libraryTemplateLogic)['props'] => ({
        id: id || 'new',
    }),
}
