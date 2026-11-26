import type { WidgetFrameApi } from '../generated/api.schemas'
import type { ViewerOutput } from './notebookAppViewerLogic'
import { viewerWidgetFrames, viewerWidgetPage } from './viewerWidgetFrames'

const output: ViewerOutput = {
    query: 'SELECT value FROM weekly',
    result: { columns: ['value'], types: [['value', 'String']], results: [['first'], ['second']] },
    generation: 1,
    widgetSlots: [{ node_id: 'card', version_id: 'active', slot: 'records' }],
}
const authorized: WidgetFrameApi = {
    sourceNodeId: 'weekly',
    name: 'records',
    runId: 'pinned',
    columns: [{ name: 'value', type: 'String' }],
    rows: [['saved']],
    includedRowCount: 1,
    totalRowCount: 1,
    truncated: false,
    nextOffset: null,
    offset: 0,
}

describe('viewer widget frames', () => {
    it('routes results to the declared placement, version and logical slot', () => {
        expect(viewerWidgetFrames({ weekly: output }, 'other', 'active').size).toBe(0)
        expect(viewerWidgetFrames({ weekly: output }, 'card', 'older').size).toBe(0)
        expect(viewerWidgetFrames({ weekly: output }, 'card', 'active').get('records')).toEqual({
            sourceNodeId: 'weekly',
            output,
        })
    })

    it('pages viewer rows and refuses a changed source or an unexpected column', () => {
        expect(viewerWidgetPage(authorized, 'weekly', output, 0, 1)).toMatchObject({
            rows: [['first']],
            nextOffset: 1,
            truncated: true,
            runId: 'pinned',
        })
        expect(viewerWidgetPage(authorized, 'weekly', output, 1, 1)).toMatchObject({
            rows: [['second']],
            nextOffset: null,
            truncated: false,
        })
        expect(() => viewerWidgetPage(authorized, 'other', output, 0, 1)).toThrow('input changed')
        expect(() => viewerWidgetPage({ ...authorized, columns: [] }, 'weekly', output, 0, 1)).toThrow(
            'columns changed'
        )
    })
})
