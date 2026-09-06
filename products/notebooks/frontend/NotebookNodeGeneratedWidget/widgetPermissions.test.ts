import {
    DEFAULT_WIDGET_PERMISSIONS,
    widgetPermissionAttributePatch,
    widgetPermissionsFromAttributes,
} from './widgetPermissions'

describe('widgetPermissions', () => {
    it('defaults to notebook data only', () => {
        expect(widgetPermissionsFromAttributes({})).toEqual(DEFAULT_WIDGET_PERMISSIONS)
    })

    it('round-trips the Widget capability attributes', () => {
        const permissions = widgetPermissionsFromAttributes({ noDataFrames: true, allowSQL: true, allowTools: true })

        expect(permissions).toEqual({ notebookData: false, hogqlQueries: true, toolCalls: true })
        expect(widgetPermissionAttributePatch(permissions)).toEqual({
            noDataFrames: true,
            allowSQL: true,
            allowTools: true,
        })
    })

    it('removes attributes for the default grants', () => {
        expect(widgetPermissionAttributePatch(DEFAULT_WIDGET_PERMISSIONS)).toEqual({
            noDataFrames: undefined,
            allowSQL: undefined,
            allowTools: undefined,
        })
    })
})
