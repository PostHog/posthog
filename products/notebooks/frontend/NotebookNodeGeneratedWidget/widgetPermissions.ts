export type WidgetPermissions = {
    notebookData: boolean
    hogqlQueries: boolean
    toolCalls: boolean
}

export const DEFAULT_WIDGET_PERMISSIONS: WidgetPermissions = {
    notebookData: true,
    hogqlQueries: false,
    toolCalls: false,
}

export type WidgetPermissionAttributes = {
    noDataFrames?: boolean
    allowSQL?: boolean
    allowTools?: boolean
}

export function widgetPermissionsFromAttributes(attributes: WidgetPermissionAttributes): WidgetPermissions {
    return {
        notebookData: attributes.noDataFrames !== true,
        hogqlQueries: attributes.allowSQL === true,
        toolCalls: attributes.allowTools === true,
    }
}

export function widgetPermissionAttributePatch(permissions: WidgetPermissions): WidgetPermissionAttributes {
    return {
        noDataFrames: permissions.notebookData ? undefined : true,
        allowSQL: permissions.hogqlQueries ? true : undefined,
        allowTools: permissions.toolCalls ? true : undefined,
    }
}

export function widgetPermissionsFromApi(
    permissions: { notebook_data?: boolean; hogql_queries?: boolean; tool_calls?: boolean } | null | undefined
): WidgetPermissions {
    return permissions
        ? {
              notebookData: permissions.notebook_data ?? true,
              hogqlQueries: permissions.hogql_queries ?? false,
              toolCalls: permissions.tool_calls ?? false,
          }
        : DEFAULT_WIDGET_PERMISSIONS
}

export function widgetPermissionsToApi(permissions: WidgetPermissions): {
    notebook_data: boolean
    hogql_queries: boolean
    tool_calls: boolean
} {
    return {
        notebook_data: permissions.notebookData,
        hogql_queries: permissions.hogqlQueries,
        tool_calls: permissions.toolCalls,
    }
}
