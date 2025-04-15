import { useMountedLogic } from 'kea'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { SceneExport } from 'scenes/sceneTypes'

import { libraryTemplateLogic } from './libraryTemplateLogic'

export function LibraryTemplate(): JSX.Element {
    const builtLogic = useMountedLogic(libraryTemplateLogic)
    const templateId = builtLogic.props.id

    return (
        <HogFunctionConfiguration
            id={templateId === 'new' ? null : templateId}
            templateId={templateId === 'new' ? 'template-new-email-template' : ''}
            displayOptions={{
                showPersonsCount: false,
                showFilters: false,
                showTesting: false,
                showEnabled: false,
                showStatus: false,
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
