import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

import { StreamlitAppViewer } from './StreamlitApp'
import { StreamlitAppEdit } from './StreamlitAppEdit'
import { StreamlitApps } from './StreamlitApps'

// Stands in for the enrollment surface, so no scene logic mounts and no request goes out.
jest.mock('~/layout/scenes/components/FeaturePreviewSceneGate', () => ({
    FeaturePreviewSceneGate: ({ config }: { config: FeaturePreviewGateConfig }) => (
        <div data-attr="feature-preview-gate">{config.flag}</div>
    ),
}))

describe('Streamlit apps scenes', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['list', <StreamlitApps key="list" />],
        ['viewer', <StreamlitAppViewer key="viewer" id="abc123" />],
        ['edit', <StreamlitAppEdit key="edit" id="abc123" />],
    ])('offers the feature preview on the %s scene instead of dead-ending on Not found', (_name, scene) => {
        render(scene)

        expect(screen.getByTestId('feature-preview-gate')).toHaveTextContent(FEATURE_FLAGS.STREAMLIT_APPS)
    })
})
