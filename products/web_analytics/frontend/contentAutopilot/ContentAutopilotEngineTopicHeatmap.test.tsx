import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ContentAutopilotEngineTopicHeatmap } from './ContentAutopilotEngineTopicHeatmap'
import { EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'
import { engineTopicGrid } from './promptsOverview'

describe('ContentAutopilotEngineTopicHeatmap', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps each answer count in its own untranslated element, so it updates under page translation', () => {
        const { container } = render(
            <ContentAutopilotEngineTopicHeatmap
                grid={engineTopicGrid(EXAMPLE_PROMPT_SET_OVERVIEW)}
                selectedTopic={null}
                onSelectTopic={() => {}}
            />
        )

        const counts = Array.from(container.querySelectorAll('[translate="no"]'), (element) => element.textContent)
        expect(counts).toHaveLength(EXAMPLE_PROMPT_SET_OVERVIEW.engine_topics.length)
        expect(counts).toContain('320')
    })
})
