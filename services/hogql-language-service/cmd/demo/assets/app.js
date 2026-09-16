const byId = (id) => document.getElementById(id)
const editor = byId('query')
const examples = [
    {
        name: 'Event fields',
        query: 'SELECT e.§\nFROM events AS e\nLIMIT 100',
        note: 'Complete after e. to explore event fields.',
    },
    {
        name: 'Valid CTE',
        query: "WITH recent AS (\n    SELECT uuid, event, timestamp\n    FROM events\n    WHERE event = '$pageview'\n)\nSELECT uuid FROM recent§",
        note: 'Validate a CTE with an unqualified projected field.',
    },
    {
        name: 'CTE completion',
        query: 'WITH recent AS (\n    SELECT uuid, event AS event_name FROM events\n)\nSELECT recent.§ FROM recent',
        note: 'Probe CTE completion. Missing projected suggestions are a service limitation.',
    },
    {
        name: 'Subquery completion',
        query: 'SELECT nested.§\nFROM (SELECT person_id, count() AS event_count FROM events GROUP BY person_id) AS nested',
        note: 'Probe derived fields. The demo shows exactly what the service supports.',
    },
    {
        name: 'Event properties',
        query: 'SELECT e.properties.$§\nFROM events AS e',
        note: 'Complete event property names from the synthetic catalog.',
    },
    {
        name: 'Person properties',
        query: 'SELECT p.properties.§\nFROM persons AS p',
        note: 'Complete person properties through a table alias.',
    },
    {
        name: 'Property pagination',
        query: 'SELECT properties.demo_property_§ FROM events',
        note: 'There are 35 matching synthetic properties. Use Load more to test pagination.',
    },
    {
        name: 'Unknown field',
        query: 'SELECT timstamp§ FROM events',
        note: 'Validate to see a typo suggestion. Click a diagnostic to select its range.',
    },
    {
        name: 'Unknown table',
        query: 'SELECT uuid FROM evnts§',
        note: 'Validate to see the unknown-table diagnostic and suggested match.',
    },
    {
        name: 'Warehouse table',
        query: 'SELECT o.§ FROM postgres.demo.orders AS o',
        note: 'Test a three-part synced-table name.',
    },
    {
        name: 'Quoted identifiers',
        query: 'SELECT c.§ FROM demo_customers AS c',
        note: 'Insert billing address or café to check identifier quoting.',
    },
    {
        name: 'Unicode diagnostic offsets',
        query: "SELECT '😀', timstamp§ FROM events",
        note: 'Validate, then click the diagnostic. The selected range should be timstamp.',
    },
]

let catalog = null
let selection = { query: '', position: 0 }
let completionSnapshot = null
let nextCursor = ''
let analysisTimer = null
let composing = false
const requests = { validation: null, completion: null }
const feedback = { validation: '', completion: '' }
const copying = { validation: false, completion: false }

function captureFeedback(kind, exchange) {
    feedback[kind] = JSON.stringify(exchange, null, 2)
    byId(`${kind}-feedback`).value = feedback[kind]
    byId(`${kind}-copy`).disabled = copying[kind]
    byId(`${kind}-copy-status`).textContent = 'Last completed request, retained when the editor changes.'
}

async function copyFeedback(kind) {
    const text = feedback[kind]
    if (!text || copying[kind]) {
        return
    }
    copying[kind] = true
    byId(`${kind}-copy`).disabled = true
    try {
        await navigator.clipboard.writeText(text)
        byId(`${kind}-copy-status`).textContent = 'Copied request and response.'
    } catch {
        byId(`${kind}-feedback-details`).open = true
        const field = byId(`${kind}-feedback`)
        field.value = text
        field.focus()
        field.select()
        byId(`${kind}-copy-status`).textContent =
            'Clipboard access is unavailable. Press Ctrl/⌘ C to copy the selected text.'
    } finally {
        copying[kind] = false
        byId(`${kind}-copy`).disabled = false
    }
}

function node(tag, text, className = '') {
    const element = document.createElement(tag)
    element.textContent = text
    element.className = className
    return element
}

function setBusy(kind, busy) {
    if (kind === 'validation') {
        byId('validate').disabled = busy
        byId('validate').textContent = busy ? 'Validating…' : 'Validate'
    } else {
        byId('complete').disabled = busy
        byId('more').disabled = busy
        byId('complete').textContent = busy ? 'Completing…' : 'Complete at cursor'
    }
}

function invalidate(kind) {
    requests[kind]?.abort()
    requests[kind] = null
    setBusy(kind, false)
    byId(`${kind}-time`).textContent = ''
    byId(`${kind}-json`).textContent = 'No request for this editor state.'
    if (kind === 'validation') {
        byId('validation').replaceChildren(node('p', 'Validate the query to see diagnostics.', 'muted'))
    } else {
        completionSnapshot = null
        nextCursor = ''
        byId('suggestions').replaceChildren()
        byId('more').hidden = true
        byId('completion-status').textContent = 'Place the cursor where you want suggestions.'
    }
}

function cancelScheduledAnalysis() {
    clearTimeout(analysisTimer)
    analysisTimer = null
}

function scheduleAnalysis() {
    cancelScheduledAnalysis()
    if (!byId('auto-analyze').checked || composing || !editor.value.trim()) {
        return
    }
    analysisTimer = setTimeout(() => {
        analysisTimer = null
        validate()
        complete()
    }, 300)
}

function syncSelection() {
    const queryChanged = selection.query !== editor.value
    if (queryChanged) {
        invalidate('validation')
    }
    if (queryChanged || selection.position !== editor.selectionStart) {
        invalidate('completion')
    }
    selection = { query: editor.value, position: editor.selectionStart }
    const before = editor.value.slice(0, editor.selectionStart)
    const lines = before.split('\n')
    byId('position').textContent =
        `Line ${lines.length}, column ${lines.at(-1).length + 1} · UTF-16 offset ${editor.selectionStart}`
    if (queryChanged) {
        scheduleAnalysis()
    }
}

async function request(kind, payload, onResult) {
    if (requests[kind]) {
        return
    }
    const controller = new AbortController()
    requests[kind] = controller
    setBusy(kind, true)
    const started = performance.now()
    const endpoint = kind === 'completion' ? 'autocomplete' : 'validate'
    const requestBody = kind === 'completion' ? { ...payload, positionEncoding: 'utf-16' } : payload
    const exchange = {
        operation: endpoint,
        recordedAt: new Date().toISOString(),
        catalogSource: 'services/hogql-language-service/cmd/demo/catalog.go',
        request: {
            method: 'POST',
            path: `/api/${endpoint}`,
            servicePath: `/teams/1/users/1/${endpoint}`,
            body: requestBody,
        },
        response: null,
    }
    try {
        const response = await fetch(`/api/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
            signal: controller.signal,
        })
        const body = await response.text()
        if (requests[kind] !== controller) {
            return
        }
        let responseBody = body
        try {
            responseBody = JSON.parse(body)
        } catch {}
        exchange.response = {
            status: response.status,
            contentType: response.headers.get('Content-Type'),
            body: responseBody,
        }
        captureFeedback(kind, exchange)
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${body}`)
        }
        const data = JSON.parse(body)
        if (requests[kind] !== controller) {
            return
        }
        byId(`${kind}-json`).textContent = JSON.stringify(data, null, 2)
        byId(`${kind}-time`).textContent =
            `${(data.durationMicros / 1000).toFixed(2)} ms service · ${(performance.now() - started).toFixed(0)} ms round trip`
        onResult(data)
    } catch (error) {
        if (controller.signal.aborted) {
            return
        }
        if (!exchange.response) {
            captureFeedback(kind, { ...exchange, error: error.message })
        }
        const message = `${error.message} Retry the request, or restart the demo if the service stopped.`
        byId(`${kind}-json`).textContent = message
        if (kind === 'validation') {
            byId('validation').replaceChildren(node('p', message, 'bad'))
        } else {
            byId('completion-status').textContent = message
        }
    } finally {
        if (requests[kind] === controller) {
            requests[kind] = null
            setBusy(kind, false)
        }
    }
}

function validate() {
    syncSelection()
    const snapshot = editor.value
    return request('validation', { query: snapshot, positionEncoding: 'utf-8' }, (data) => {
        const queryBytes = new TextEncoder().encode(snapshot)
        const editorOffset = (byteOffset) => new TextDecoder().decode(queryBytes.subarray(0, byteOffset)).length
        const result = byId('validation')
        result.replaceChildren(
            node(
                'p',
                data.valid ? 'Valid according to the Go service.' : `${data.diagnostics.length} diagnostic(s)`,
                data.valid ? 'good' : 'bad'
            )
        )
        result.append(node('p', `Referenced tables: ${data.tableNames?.join(', ') || 'none'}`, 'hint'))
        for (const diagnostic of data.diagnostics) {
            const button = node('button', diagnostic.message, 'diagnostic')
            button.type = 'button'
            button.append(node('small', `${diagnostic.code} · UTF-8 bytes ${diagnostic.start}–${diagnostic.end}`))
            if (diagnostic.suggestions?.length) {
                button.append(node('small', `Suggestions: ${diagnostic.suggestions.map((s) => s.label).join(', ')}`))
            }
            button.addEventListener('click', () => {
                if (editor.value !== snapshot) {
                    return
                }
                editor.focus()
                editor.setSelectionRange(editorOffset(diagnostic.start), editorOffset(diagnostic.end))
                syncSelection()
            })
            result.append(button)
        }
    })
}

function insertSuggestion(suggestion, snapshot) {
    if (editor.value !== snapshot.query || editor.selectionStart !== snapshot.position) {
        return
    }
    const before = snapshot.query.slice(0, snapshot.position)
    const prefix = before.match(/[\p{L}\p{N}_$]*$/u)[0]
    const suffix = snapshot.query.slice(snapshot.position).match(/^[\p{L}\p{N}_$]*/u)[0]
    editor.focus()
    editor.setRangeText(
        suggestion.insertText || suggestion.label,
        snapshot.position - prefix.length,
        snapshot.position + suffix.length,
        'end'
    )
    syncSelection()
}

function complete(more = false) {
    syncSelection()
    if (requests.completion) {
        return
    }
    const snapshot = { ...selection }
    const cursor = more ? nextCursor : ''
    if (more && (!completionSnapshot || !cursor)) {
        return
    }
    if (!more) {
        byId('suggestions').replaceChildren()
        byId('more').hidden = true
    }
    return request('completion', { ...snapshot, cursor }, (data) => {
        completionSnapshot = snapshot
        nextCursor = data.nextCursor || ''
        for (const suggestion of data.suggestions || []) {
            const button = node('button', '', 'suggestion')
            button.type = 'button'
            button.append(node('span', suggestion.label), node('small', suggestion.detail || suggestion.kind))
            button.title = `Insert ${suggestion.insertText || suggestion.label}`
            button.addEventListener('click', () => insertSuggestion(suggestion, snapshot))
            byId('suggestions').append(button)
        }
        const shown = byId('suggestions').childElementCount
        byId('completion-status').textContent = data.total
            ? `${shown} of ${data.total} suggestions. Click to insert.`
            : 'No suggestions at this cursor. Check the catalog or try another example.'
        if (data.parseError) {
            byId('completion-status').textContent += ` Parser: ${data.parseError}`
        }
        byId('more').hidden = !nextCursor
    })
}

function renderCatalog() {
    if (!catalog) {
        return
    }
    const filter = byId('catalog-filter').value.toLowerCase()
    const root = byId('catalog')
    root.replaceChildren()
    const groups = Object.entries(catalog.tables).map(([name, table]) => [name, Object.values(table.fields)])
    for (const [name, properties] of Object.entries(catalog.properties)) {
        groups.push([`${name} properties`, properties.map((p) => ({ name: p.name, type: p.property_type }))])
    }
    for (const [name, fields] of groups) {
        const visible = fields.filter((field) => `${name} ${field.name}`.toLowerCase().includes(filter))
        if (!visible.length) {
            continue
        }
        const details = node('details', '')
        details.open = !!filter || name === 'events'
        details.append(node('summary', `${name} (${visible.length})`))
        for (const field of visible.sort((a, b) => a.name.localeCompare(b.name))) {
            const row = node('div', '', 'catalog-field')
            row.append(node('span', field.name), node('span', field.type))
            details.append(row)
        }
        root.append(details)
    }
    if (!root.childElementCount) {
        root.append(node('p', 'No matching fields. Try another search.', 'muted'))
    }
}

function loadExample() {
    const example = examples[Number(byId('example').value)]
    const position = example.query.indexOf('§')
    editor.value = example.query.replace('§', '')
    editor.focus()
    editor.setSelectionRange(position, position)
    byId('example-note').textContent = example.note
    syncSelection()
}

for (const [index, example] of examples.entries()) {
    const option = node('option', example.name)
    option.value = String(index)
    byId('example').append(option)
}
byId('example').addEventListener('change', loadExample)
byId('validate').addEventListener('click', validate)
byId('complete').addEventListener('click', () => complete())
byId('more').addEventListener('click', () => complete(true))
byId('catalog-filter').addEventListener('input', renderCatalog)
for (const kind of Object.keys(feedback)) {
    byId(`${kind}-copy`).addEventListener('click', () => copyFeedback(kind))
}
byId('auto-analyze').addEventListener('change', () => {
    scheduleAnalysis()
    if (!byId('auto-analyze').checked) {
        for (const kind of Object.keys(requests)) {
            if (requests[kind]) {
                invalidate(kind)
            }
        }
    }
})
editor.addEventListener('compositionstart', () => {
    composing = true
    cancelScheduledAnalysis()
})
editor.addEventListener('compositionend', () => {
    composing = false
    syncSelection()
    scheduleAnalysis()
})
window.addEventListener('pagehide', () => {
    cancelScheduledAnalysis()
    for (const kind of Object.keys(requests)) {
        if (requests[kind]) {
            invalidate(kind)
        }
    }
})
for (const event of ['input', 'keyup', 'click', 'select']) {
    editor.addEventListener(event, syncSelection)
}
editor.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault()
        if (event.shiftKey) {
            complete()
        } else {
            validate()
        }
    }
})
loadExample()
fetch('/api/catalog')
    .then(async (response) => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`)
        }
        const publication = await response.json()
        catalog = publication.catalog
        renderCatalog()
        byId('connection').textContent =
            `${Object.keys(catalog.tables).length} synthetic tables loaded · ${publication.revision}`
    })
    .catch((error) => {
        byId('connection').textContent =
            `Could not load the catalog: ${error.message}. Refresh the page or restart the demo.`
    })
