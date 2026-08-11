import notebookWidgetCatalog from 'products/notebooks/notebook-widget-catalog.json'

type NotebookWidgetTagName = keyof typeof notebookWidgetCatalog.widgets

export function getNotebookWidgetTagNames(): NotebookWidgetTagName[] {
    return Object.keys(notebookWidgetCatalog.widgets) as NotebookWidgetTagName[]
}

export function getNotebookWidgetViewNames(tagName: string): string[] | null {
    const widgets = notebookWidgetCatalog.widgets as Record<
        string,
        { defaultView: { name: string }; views: Record<string, unknown> }
    >
    const widget = widgets[tagName]
    return widget ? [widget.defaultView.name, ...Object.keys(widget.views)] : null
}

export function getNotebookWidgetViewError(tagName: string, view: unknown): string | null {
    const viewNames = getNotebookWidgetViewNames(tagName)
    if (!viewNames || view === undefined) {
        return null
    }
    if (typeof view !== 'string' || !viewNames.includes(view)) {
        return `${tagName} view must be one of: ${viewNames.join(', ')}.`
    }
    return null
}

export function formatNotebookWidgetCatalogForAgents(): string {
    const widgetLines = getNotebookWidgetTagNames().map((tagName) => {
        const widget = notebookWidgetCatalog.widgets[tagName]
        const views = [widget.defaultView, ...Object.entries(widget.views).map(([name, view]) => ({ name, ...view }))]
            .map((view) => `${view.name}: ${view.description}`)
            .join(' ')
        const exampleProps = {
            [widget.idProp]: widget.idExample,
            view: 'summary',
        }
        const markdownId =
            typeof widget.idExample === 'number' ? `{${widget.idExample}}` : JSON.stringify(widget.idExample)
        const markdownExample = `<${tagName} ${widget.idProp}=${markdownId} view="summary" />`
        const richTextExample = JSON.stringify({ type: widget.nodeType, attrs: exampleProps })

        return `- ${tagName}: ${widget.description} Identity: ${widget.idDescription} Markdown: ${markdownExample}. Rich text: ${richTextExample}. Views: ${views}`
    })

    return [
        'Notebook object widgets use shared view names. Use summary for compact supporting context, detail when the object is the main subject, and a specialized view when it directly answers the task.',
        'Filters are hidden by default. Add showFilters only when the reader should configure the widget. Results are shown by default. Add hideResults only when the result should be collapsed.',
        ...widgetLines,
    ].join('\n')
}
