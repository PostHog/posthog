import schema from '~/queries/schema.json'

import { MAX_ROWS_PER_STEP_BOUNDS, MAX_STEP_SOURCES, MAX_STEPS_BOUNDS } from './editorBounds'

describe('journeys editor bounds', () => {
    // The server rejects out-of-bounds values instead of clamping, so drifted editor bounds either
    // block values the server accepts or let through values the server rejects.
    it('match the PathsV2Filter schema bounds', () => {
        const properties = (schema as any).definitions.PathsV2Filter.properties
        expect(MAX_STEPS_BOUNDS).toEqual({ min: properties.maxSteps.minimum, max: properties.maxSteps.maximum })
        expect(MAX_ROWS_PER_STEP_BOUNDS).toEqual({
            min: properties.maxRowsPerStep.minimum,
            max: properties.maxRowsPerStep.maximum,
        })
        expect(MAX_STEP_SOURCES).toBe(properties.stepSources.maxItems)
    })
})
