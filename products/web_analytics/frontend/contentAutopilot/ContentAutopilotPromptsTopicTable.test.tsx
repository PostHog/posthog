import { cleanup, fireEvent, render, within } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ContentAutopilotPromptsTopicTable } from './ContentAutopilotPromptsTopicTable'
import { EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'

describe('ContentAutopilotPromptsTopicTable', () => {
    beforeEach(() => {
        // Clicking a Link pushes to the kea router, so the router logic must be live
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const row = EXAMPLE_PROMPT_SET_OVERVIEW.topics.find((topic) => topic.topic)!

    it.each([
        ['the topic link', (): string => row.topic],
        ['another cell of the row', (): string => String(row.active_prompts)],
    ])('selects the topic once when %s is clicked', (_, text) => {
        const onSelect = jest.fn()
        const { container } = render(
            <ContentAutopilotPromptsTopicTable rows={[row]} selectedTopic={null} onSelect={onSelect} />
        )

        fireEvent.click(within(container).getByText(text()))

        expect(onSelect).toHaveBeenCalledTimes(1)
        expect(onSelect).toHaveBeenCalledWith(row.topic)
    })
})
