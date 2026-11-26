// The script-side View SDK, evaluated before every view script.
// Scripts build plain element trees; the host renders them with GPUI.
// Everything that leaves the script goes through __host_* functions, and
// every broker call is checked against this view's permissions.
'use strict'
var __def = null,
    __state = {},
    __handlers = new Map(),
    __nextHandler = 0
var __pending = new Map(),
    __nextCall = 0
var __validatingInit = false,
    __initValidationError = null
var __menuKeys = {}
var __timers = new Map(),
    __nextTimer = 0
var __inBadge = false,
    __badgeLive
function __effect() {
    if (__inBadge) throw new Error('badge must be pure')
}
for (const name of ['__host_request', '__host_local', '__host_dirty']) {
    globalThis[name] = new Proxy(globalThis[name], {
        apply(target, receiver, args) {
            __effect()
            return Reflect.apply(target, receiver, args)
        },
    })
}

function __fmt(v) {
    if (typeof v === 'string') return v
    if (v instanceof Error) return String(v.stack ? v.message + '\n' + v.stack : v)
    try {
        return JSON.stringify(v)
    } catch (e) {
        return String(v)
    }
}
var console = {
    log: (...a) => __host_log(a.map(__fmt).join(' ')),
    info: (...a) => __host_log(a.map(__fmt).join(' ')),
    debug: (...a) => __host_log(a.map(__fmt).join(' ')),
    warn: (...a) => __host_log('warn: ' + a.map(__fmt).join(' ')),
    error: (...a) => __host_log('error: ' + a.map(__fmt).join(' ')),
}
globalThis.console = console

// ---- View definition and state ---------------------------------------------
function view(def) {
    if (__def) throw new Error('view() may only be called once')
    if (!def || typeof def.render !== 'function')
        throw new Error('Call view({ state, init, render(state), commands, keys })')
    __def = def
}
function setState(patch) {
    __effect()
    const next = typeof patch === 'function' ? patch(__state) : patch
    if (next == null) return
    if (typeof next !== 'object' || Array.isArray(next)) throw new Error('setState expects an object')
    __state = Object.assign({}, __state, next)
    __host_dirty()
}
function getState() {
    return __state
}

// ---- Host capabilities ---------------------------------------------------------
function __request(method, params) {
    // Leave host calls pending in the throwaway validation engine. Their
    // results cannot be known without performing external work.
    if (__validatingInit) return new Promise(() => {})
    __effect()
    return new Promise((resolve, reject) => {
        const id = ++__nextCall
        __pending.set(id, { resolve, reject })
        __host_request(id, method, JSON.stringify(params === undefined ? {} : params))
    })
}
function __local(kind, value) {
    // Window effects (including timers) are captured by omission here.
    if (__validatingInit) return
    __effect()
    __host_local(kind, JSON.stringify(value === undefined ? null : value))
}
function __cliRequest(id, args, options, reference) {
    const params = { id, args: args || [] }
    if (options?.timeoutMs) params.timeout_ms = options.timeoutMs
    if (options?.pattern) params.pattern = options.pattern
    if (reference) params.cli_reference = reference
    return __request('cli.run', params)
}
var host = {
    // MCP tools and REST/GraphQL API actions, checked against this view's grants.
    call: (source, tool, args) => __request('sources.call', { source, tool, arguments: args || {} }),
    // Run a permitted CLI action by grant ID or executable name, with string args.
    cli: (id, args, options) => __cliRequest(id, args, options),
    // Sources and tools this view may call right now.
    sources: () => __request('sources.list', {}),
    // Input schemas for a source's permitted tools.
    describe: (source) => __request('sources.describe', { source }),
    // CLI actions this view may run.
    cliActions: () => __request('cli.list', {}),
    // This view's grants plus every connected source and installed CLI, so a
    // view can explain what it is missing.
    permissions: () => __request('permissions.inspect', {}),
    // Ask the user for access. Resolves to true only when they allow it.
    //   { kind: "mcp", source, tool, reason }
    //   { kind: "cli", tool_id, action: ["pr", "list"], reason }
    request: (change) => __request('permissions.request', change).then((r) => !!(r && r.approved)),
    openUrl: (url) => {
        if (!/^(https?|mailto):/i.test(String(url))) throw new Error('openUrl accepts http, https and mailto URLs')
        __local('open_url', String(url))
    },
    copy: (text) => __local('copy', String(text)),
    // Move keyboard focus to the Input or Textarea with this id.
    focus: (id) => __local('focus', String(id)),
}
function __settle(id, ok, text) {
    const p = __pending.get(id)
    if (!p) return
    __pending.delete(id)
    if (ok) p.resolve(JSON.parse(text))
    else p.reject(new Error(text))
}

// ---- Timers ------------------------------------------------------------------
function __timer(fn, ms, repeat, args) {
    __effect()
    if (typeof fn !== 'function') throw new Error('Timers need a function')
    if (__timers.size >= 64) throw new Error('Too many timers (64)')
    const id = ++__nextTimer
    const delay = Math.max(repeat ? 16 : 0, Number(ms) || 0)
    __timers.set(id, { fn, args, repeat, delay })
    __local('timer', { id, ms: delay })
    return id
}
function setTimeout(fn, ms, ...args) {
    return __timer(fn, ms, false, args)
}
function setInterval(fn, ms, ...args) {
    return __timer(fn, ms, true, args)
}
function clearTimeout(id) {
    __effect()
    __timers.delete(id)
}
function __discardTimers(ids) {
    for (const id of ids) __timers.delete(id)
}
var clearInterval = clearTimeout
function __fire(id) {
    const t = __timers.get(id)
    if (!t) return
    if (t.repeat) __local('timer', { id, ms: t.delay })
    else __timers.delete(id)
    __async(t.fn(...t.args))
}

// ---- Elements ----------------------------------------------------------------
function __children(list) {
    return list.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false && c !== true && c !== '')
}
function __el(type) {
    return function (props, ...children) {
        if (props === undefined || props === null) props = {}
        else if (typeof props !== 'object' || Array.isArray(props) || props.__t) {
            children.unshift(props)
            props = {}
        }
        return { __t: type, props, children: __children(children) }
    }
}
function __leaf(type, key) {
    return function (value, props) {
        const p = Object.assign({}, props || {})
        if (value !== undefined && value !== null) p[key] = typeof value === 'string' ? value : String(value)
        return { __t: type, props: p, children: [] }
    }
}
function __props(type) {
    return (props) => ({ __t: type, props: props || {}, children: [] })
}

// Layout
var Page = __el('page'),
    Column = __el('column'),
    Row = __el('row'),
    Box = __el('box'),
    Scroll = __el('scroll'),
    Card = __el('card')
var Form = __el('form'),
    Reading = __el('reading')
// Motion: `Reveal({ open }, ...children)` opens and closes its height smoothly.
var Reveal = __el('reveal')
// Overlays: the first child is the trigger, the rest is the content, built
// only while open. Accordion: one child per item in `items`.
var HoverCard = __el('hover_card'),
    Popover = __el('popover'),
    Accordion = __el('accordion')
// Native components.
var RadioGroup = __props('radio_group'),
    Rating = __props('rating'),
    Slider = __props('slider')
var Pagination = __props('pagination'),
    Breadcrumb = __props('breadcrumb'),
    DescriptionList = __props('description_list')
var Skeleton = __props('skeleton'),
    Spinner = __props('spinner')
var Markdown = __leaf('markdown', 'text')
function Image(source, props) {
    return { __t: 'image', props: Object.assign({}, props || {}, { source }), children: [] }
}
var Kbd = __leaf('kbd', 'keys'),
    Tag = __leaf('tag', 'text'),
    Avatar = __leaf('avatar', 'name')
function Field(props, control) {
    return { __t: 'field', props: props || {}, children: __children([control]) }
}
function Actions(props, ...buttons) {
    return { __t: 'actions', props: props || {}, children: __children(buttons) }
}
function Section(title, detail) {
    return { __t: 'section', props: { title: String(title || ''), detail: String(detail || '') }, children: [] }
}
function Header(props, ...actions) {
    return { __t: 'header', props: props || {}, children: __children(actions) }
}
// Text
var Text = __leaf('text', 'text'),
    Heading = __leaf('heading', 'text'),
    Caption = __leaf('caption', 'text'),
    Mono = __leaf('mono', 'text'),
    Label = __leaf('label', 'text'),
    Badge = __leaf('badge', 'text')
var Icon = __leaf('icon', 'name'),
    Logo = __leaf('logo', 'service'),
    Link = __leaf('link', 'text')
function ReadOnly(label, value, props) {
    return {
        __t: 'read_only',
        props: Object.assign({}, props || {}, { label: String(label), value: String(value) }),
        children: [],
    }
}
// Controls
var Button = __leaf('button', 'label')
function IconButton(icon, props) {
    return {
        __t: 'icon_button',
        props: Object.assign(__checkingProps ? {} : { label: icon }, props || {}, { icon }),
        children: [],
    }
}
var Input = __props('input'),
    Textarea = __props('textarea'),
    Checkbox = __props('checkbox'),
    Toggle = __props('toggle')
// A Notion-style document editor. `value` is an array of blocks
// ({ id, type, text, marks, checked, indent }); `markdown` is accepted instead.
var WorkflowEditor = __props('workflow_editor')
var WorkflowOutline = __props('workflow_outline')
var BlockEditor = __props('block_editor')
function toMarkdown(blocks) {
    return __host_markdown('to', JSON.stringify(blocks || []))
}
function fromMarkdown(text) {
    return JSON.parse(__host_markdown('from', String(text === undefined || text === null ? '' : text)))
}
var Select = __props('select'),
    Tabs = __props('tabs'),
    Progress = __props('progress')
// Feedback and structure
var Divider = __props('divider')
function Spacer() {
    return { __t: 'spacer', props: {}, children: [] }
}
function Empty(title, detail) {
    return { __t: 'empty', props: { title: String(title || ''), detail: String(detail || '') }, children: [] }
}
function Loading() {
    return { __t: 'loading', props: {}, children: [] }
}
function ErrorMessage(text) {
    return { __t: 'error', props: { text: String(text || '') }, children: [] }
}
function Notice(title, detail) {
    return { __t: 'notice', props: { title: String(title || ''), detail: String(detail || '') }, children: [] }
}
var List = __props('list'),
    Table = __props('table')
const __dataRead = Object.freeze(
    Object.fromEntries(
        ['count', 'rows', 'aggregate'].map((op) => [
            op,
            (name, query) => JSON.parse(__host_data(op, String(name), JSON.stringify(query || {}))),
        ])
    )
)
host.data = Object.freeze(
    Object.assign(
        {},
        __dataRead,
        Object.fromEntries(
            ['set', 'patch', 'remove', 'clear'].map((op) => [
                op,
                (name, rows, options) => {
                    __effect()
                    const args =
                        op === 'remove' ? { keys: rows } : op === 'clear' ? {} : { rows, options: options || {} }
                    return JSON.parse(__host_data(op, String(name), JSON.stringify(args)))
                },
            ])
        )
    )
)
// Native scenes: millions of nodes and edges as typed arrays, drawn natively.
host.scene = Object.freeze({
    set: (name, columns) => {
        __effect()
        return JSON.parse(__host_scene('set', String(name), columns || {}))
    },
    patch: (name, columns) => {
        __effect()
        return JSON.parse(__host_scene('patch', String(name), columns || {}))
    },
    clear: (name) => {
        __effect()
        return JSON.parse(__host_scene('clear', String(name), {}))
    },
    info: (name) => JSON.parse(__host_scene('info', String(name), {})),
})
var Scene = __props('scene'),
    Chart = __props('chart'),
    ModelSelector = __props('model_selector')
function ListRow(title, subtitle, props) {
    return {
        __t: 'list_row',
        props: Object.assign({}, props || {}, {
            title: String(title == null ? '' : title),
            subtitle: String(subtitle == null ? '' : subtitle),
        }),
        children: [],
    }
}

// Only install/edit engines enable this. Saved views keep their original
// permissive constructors, and ordinary rendering never captures stacks.
var __checkingProps = false
function __checkConstructors(entries) {
    __checkingProps = true
    for (const [kind, name] of entries) {
        const original = globalThis[name]
        if (typeof original !== 'function') continue
        globalThis[name] = function (...args) {
            const at = (new Error().stack || '').match(/view\.js:\d+(?::\d+)?/)
            const location = at ? at[0] : 'view.js (render)'
            const encode = (value) => JSON.stringify(value, (k, v) => (typeof v === 'function' ? { $fn: 0 } : v))
            if (kind.startsWith('sdk:')) __host_check_props(kind, encode(args[0] || {}), location)
            const node = original(...args)
            if (!kind.startsWith('sdk:') && node && node.__t) {
                __host_check_props(kind, encode(node.props), location)
                node.__at = location
            }
            return node
        }
    }
}

// ---- Host entry points -------------------------------------------------------
function __emit(node) {
    if (typeof node === 'string' || typeof node === 'number') return { t: 'text', p: { text: String(node) }, c: [] }
    if (!node || typeof node !== 'object' || !node.__t)
        throw new Error('render must return elements such as Column(...), got ' + __fmt(node))
    if ((node.__t === 'action_menu' || node.__t === 'context_menu') && typeof node.props.onAction === 'function') {
        for (const item of node.props.items || [])
            if (item.shortcut && !item.disabled && !node.props.disabled)
                __menuKeys[item.shortcut] = () => node.props.onAction(item.id)
    }
    const p = {}
    for (const k in node.props) {
        const v = node.props[k]
        if (typeof v === 'function') {
            const id = ++__nextHandler
            __handlers.set(id, v)
            p[k] = { $fn: id }
        } else if (k === 'columns' && node.__t === 'table')
            p[k] = v.map((column) => {
                const c = Object.assign({}, column)
                if (typeof c.cell === 'function') {
                    const id = ++__nextHandler
                    __handlers.set(id, c.cell)
                    c.cell = { $fn: id }
                }
                return c
            })
        else if (v !== undefined) p[k] = v
    }
    return { t: node.__t, p, c: node.children.map(__emit), at: node.__at }
}
function __async(r) {
    if (r && typeof r.then === 'function') r.then(null, (e) => console.error(e))
}
function __ready() {
    if (!__def) throw new Error('The script must call view({ render(state) { ... } })')
}
function __boot(saved) {
    const base = typeof __def.state === 'function' ? __def.state() : __def.state || {}
    const restored = JSON.parse(saved)
    __state = Object.assign(
        {},
        base,
        restored && typeof restored === 'object' && !Array.isArray(restored) ? restored : {}
    )
}
function __needs() {
    return JSON.stringify(__def.needs === undefined ? [] : __def.needs)
}
var __initRun = 0,
    __initializing = false
// Needs the host adds for this view: what it used before it was imported.
var __hostNeeds = []
function __setHostNeeds(json) {
    const needs = JSON.parse(json)
    __hostNeeds = Array.isArray(needs) ? needs : []
}
function __init_pending() {
    return __initializing
}
function __initErrorText(e) {
    const message = e && e.message ? String(e.name || 'Error') + ': ' + String(e.message) : String(e)
    const stack = e && e.stack ? String(e.stack) : ''
    return (stack.includes(message) ? stack : message + (stack ? '\n' + stack : '')) || 'an empty value'
}
function __validateInit() {
    __validatingInit = true
    __initValidationError = null
    try {
        const result = __def.init && __def.init()
        if (result && typeof result.then === 'function')
            Promise.resolve(result).then(undefined, (e) => {
                __initValidationError = __initErrorText(e)
            })
    } catch (e) {
        __initValidationError = __initErrorText(e)
    }
    // This flag stays set while promise jobs run. This engine is disposable.
}
function __init_validation_error() {
    return __initValidationError
}
function __init() {
    const run = ++__initRun
    __initializing = true
    const start = () => {
        if (__def.init) return __def.init()
    }
    let result
    try {
        const declared = __def.needs || []
        const key = (need) => JSON.stringify(need)
        const imported = __hostNeeds.filter((need) => !declared.some((d) => key(d) === key(need)))
        const needs = declared.concat(imported)
        result = needs.length
            ? host
                  .request({
                      kind: 'needs',
                      needs,
                      reason: imported.length
                          ? 'What this view used where it came from, so it can load its data here.'
                          : 'Declared by the view so it can load its data.',
                  })
                  .catch((e) => console.error(e))
                  .then(start)
            : start()
    } catch (e) {
        __initializing = false
        throw e
    }
    if (result && typeof result.then === 'function')
        result.then(
            () => {
                if (__initRun === run) __initializing = false
            },
            (e) => {
                if (__initRun === run) __initializing = false
                console.error(e)
            }
        )
    else __initializing = false
}
function __render() {
    __menuKeys = {}
    __handlers.clear()
    return JSON.stringify(__emit(__def.render(__state)))
}
function __row(fn, i) {
    const f = __handlers.get(fn)
    if (!f) throw new Error('List row function expired')
    return JSON.stringify(__emit(f(i)))
}
function __cell(fn, row) {
    return JSON.stringify(__emit(__handlers.get(fn)(JSON.parse(row))))
}
function __invoke(id, arg) {
    const f = __handlers.get(id)
    if (f) __async(f(JSON.parse(arg)))
}
function __key(name) {
    const f = (__def.keys && __def.keys[name]) || __menuKeys[name]
    if (typeof f !== 'function') return false
    return (__async(f()), true)
}
function __command(name, arg) {
    const c =
        name === '@workflow.execute'
            ? (args) => host.workflows.execute(args.id, args.input)
            : (__def.commands || {})[name]
    if (typeof c !== 'function') throw new Error('Unknown command ' + name)
    const r = c(JSON.parse(arg))
    __async(r)
    return JSON.stringify(r === undefined || (r && typeof r.then === 'function') ? null : r)
}
function __commands() {
    return JSON.stringify(Object.keys(__def.commands || {}).filter((k) => typeof __def.commands[k] === 'function'))
}
function __has_command(name) {
    return typeof (__def.commands || {})[name] === 'function'
}
function __inspect() {
    const v = __def.inspect ? __def.inspect(__state) : __state
    return JSON.stringify(
        Object.assign({}, v && typeof v === 'object' ? v : { value: v }, {
            commands: Object.keys(__def.commands || {}),
            keys: Object.keys(__def.keys || {}),
        })
    )
}
function __checkpoint() {
    return JSON.stringify(__state)
}
function __restore(saved) {
    if (typeof __agentReset === 'function') __agentReset()
    __workflowEpoch++
    __state = JSON.parse(saved)
    __pending.clear()
    __background.clear()
    __backgroundJobs.clear()
    __timers.clear() // The host retires the previous epoch's timer tasks.
    __host_dirty()
}
function __badge(before) {
    const live = __state
    const freeze = (v) => {
        if (v && typeof v === 'object') {
            for (const key of Object.keys(v)) v[key] = freeze(v[key])
            Object.freeze(v)
            return new Proxy(v, {
                set() {
                    throw Error('badge must be pure')
                },
                deleteProperty() {
                    throw Error('badge must be pure')
                },
                defineProperty() {
                    throw Error('badge must be pure')
                },
                setPrototypeOf() {
                    throw Error('badge must be pure')
                },
            })
        }
        return v
    }
    __badgeLive = live
    __inBadge = true
    try {
        __state = freeze(JSON.parse(before))
        const value = __def.badge ? __def.badge(__state, __dataRead) : null
        if (value && typeof value.then === 'function') throw Error('badge must be synchronous')
        // Serialize fields independently: a cyclic/non-JSON argument must not
        // discard an otherwise valid value or summary. Limits stay in the host.
        if (value && typeof value === 'object') {
            const read = (obj, key) => {
                try {
                    return obj[key]
                } catch (_) {
                    return undefined
                }
            }
            const field = (obj, key) => {
                try {
                    return JSON.parse(JSON.stringify(read(obj, key)))
                } catch (_) {
                    return undefined
                }
            }
            const items = read(value, 'items')
            return JSON.stringify({
                value: field(value, 'value'),
                title: field(value, 'title'),
                items: Array.isArray(items)
                    ? items.map((item) =>
                          item && typeof item === 'object'
                              ? {
                                    label: field(item, 'label'),
                                    detail: field(item, 'detail'),
                                    marker: field(item, 'marker'),
                                    command: field(item, 'command'),
                                    args: field(item, 'args'),
                                }
                              : null
                      )
                    : undefined,
            })
        }
        return JSON.stringify(value)
    } catch (e) {
        console.error(e)
        return 'null'
    }
}
function __badge_end(before) {
    __state = __badgeLive
    let changed
    try {
        changed = JSON.stringify(__state) !== before
    } catch (_) {
        changed = true
    }
    if (changed) __state = JSON.parse(before)
    __badgeLive = undefined
    __inBadge = false
    return changed
}

// Native SDK v1: stable JSON contracts; all effects are scoped broker requests.
const __native = (method, params) => __request('native.' + method, params)
host.ai = Object.freeze({ run: (options) => __native('ai.run', options) })
host.native = Object.freeze({ info: () => __native('info', {}) })
host.confirm = (options) => __native('confirm', options)
host.toast = Object.freeze({
    show: (options) => __native('toast.show', options),
    update: (options) => __native('toast.update', options),
    dismiss: (id) => __native('toast.dismiss', { id }),
})
host.notifications = Object.freeze({
    authorization: () => __native('notifications.authorization', {}),
    requestAuthorization: () => __native('notifications.requestAuthorization', {}),
    send: (options) => __native('notifications.send', options),
    list: () => __native('notifications.list', {}),
    dismiss: (id) => __native('notifications.dismiss', { id }),
})
host.reminders = Object.freeze({
    schedule: (options) => __native('reminders.schedule', options),
    list: () => __native('reminders.list', {}),
    cancel: (id) => __native('reminders.cancel', { id }),
    snooze: (id, delayMs) => __native('reminders.snooze', { id, delayMs }),
})
host.background = Object.freeze({
    register: (options) => __native('background.register', options),
    list: () => __native('background.list', {}),
    unregister: (id) => __native('background.unregister', { id }),
    setEnabled: (id, enabled) => __native('background.setEnabled', { id, enabled }),
})
host.workflows = Object.freeze({
    register: (definition) => __native('workflows.register', definition),
    update: (definition, options) =>
        __native(
            'workflows.update',
            options && options.expected ? { definition, expected: options.expected } : definition
        ),
    list: () => __native('workflows.list', {}),
    run: (id, input) => __native('workflows.run', { id, input: input === undefined ? null : input }),
    execute: (id, input) => __executeWorkflow(id, input === undefined ? null : input),
    unregister: (id) => __native('workflows.unregister', { id }),
    setEnabled: (id, enabled) => __native('workflows.setEnabled', { id, enabled }),
})
host.files = Object.freeze({
    pick: (options) => __native('files.pick', options || {}),
    pickFolder: (options) => __native('files.pickFolder', options || {}),
    list: (id, options) => __native('files.list', { ...(options || {}), id }),
    stat: (id, options) => __native('files.stat', { path: options?.path ?? null, id }),
    readText: (id, options) =>
        __native('files.readText', options === undefined ? { id } : { path: options?.path ?? null, id }),
    release: (id) => __native('files.release', { id }),
    saveText: (options) => __native('files.saveText', options),
})
host.clipboard = Object.freeze({
    readText: () => __native('clipboard.readText', {}),
    paste: (text, options) => __native('clipboard.paste', { text, delayMs: options?.delayMs }),
    copy: host.copy,
})
host.selection = Object.freeze({ readText: (options) => __native('selection.readText', { delayMs: options?.delayMs }) })
host.apps = Object.freeze({ open: (url) => __native('apps.open', { url }) })
host.calendar = Object.freeze({
    authorization: () => __native('calendar.authorization', {}),
    calendars: () => __native('calendar.calendars', {}),
    events: (options) => __native('calendar.events', options),
    create: (options) => __native('calendar.create', options),
})
host.systemReminders = Object.freeze({
    authorization: () => __native('systemReminders.authorization', {}),
    lists: () => __native('systemReminders.lists', {}),
    items: (options) => __native('systemReminders.items', options ?? {}),
    create: (options) => __native('systemReminders.create', options),
})
host.contacts = Object.freeze({
    authorization: () => __native('contacts.authorization', {}),
    search: (options) => __native('contacts.search', options),
    get: (id) => __native('contacts.get', { id }),
})
host.mail = Object.freeze({
    authorization: () => __native('mail.authorization', {}),
    mailboxes: () => __native('mail.mailboxes', {}),
    messages: (options) => __native('mail.messages', options ?? {}),
    message: (id) => __native('mail.message', { id }),
})
var ActionMenu = __props('action_menu'),
    ContextMenu = __el('context_menu'),
    DatePicker = __props('date_picker'),
    TimePicker = __props('time_picker')
var __background = new Map(),
    __backgroundJobs = new Map(),
    __nextBackground = 0
function __backgroundStart(name, args) {
    if (__backgroundJobs.has(name)) throw Error('Background job is already in flight: ' + name)
    const fn =
        name === '@workflow'
            ? (input) =>
                  input.definition.version === 2
                      ? __native('workflows.execute', input)
                      : __runWorkflow(input, () => __background.has(id))
            : (__def.commands || {})[name]
    if (typeof fn !== 'function') throw Error('Unknown background command ' + name)
    const id = ++__nextBackground,
        slot = { done: false }
    __background.set(id, { name, slot })
    __backgroundJobs.set(name, id)
    Promise.resolve()
        .then(() => fn(JSON.parse(args)))
        .then(
            (value) => {
                Object.assign(slot, { done: true, value: value === undefined ? null : value })
            },
            (error) => {
                Object.assign(slot, { done: true, error: String(error.message || error) })
            }
        )
    return id
}
function __backgroundCancel(id, requests) {
    for (const request of requests) __pending.delete(request)
    const entry = __background.get(id)
    if (!entry) return
    __background.delete(id)
    if (__backgroundJobs.get(entry.name) === id) __backgroundJobs.delete(entry.name)
}
function __backgroundResult(id, collect) {
    const entry = __background.get(id)
    if (!entry) throw Error('Unknown background invocation ' + id)
    const result = JSON.stringify(entry.slot)
    if (collect) {
        if (!entry.slot.done) throw Error('Background invocation is still in flight')
        __background.delete(id)
        if (__backgroundJobs.get(entry.name) === id) __backgroundJobs.delete(entry.name)
    }
    return result
}

// Data-only workflow interpreter. References are JSON pointers, never code.
async function __runWorkflow({ definition, input }, alive) {
    if (!definition || definition.version !== 1) throw Error('Unsupported workflow version')
    const outputs = Object.create(null)
    const own = (value, key) =>
        value != null && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, key)
    const resolve = (value) => {
        if (Array.isArray(value)) return value.map(resolve)
        if (!value || typeof value !== 'object') return value
        if (own(value, '$ref')) {
            let result = { input, state: getState(), steps: outputs }
            for (const part of value.$ref.slice(1).split('/')) {
                const key = part.replace(/~1/g, '/').replace(/~0/g, '~')
                if (!own(result, key)) {
                    if (own(value, 'default')) return resolve(value.default)
                    throw Error('Missing reference ' + value.$ref)
                }
                result = result[key]
            }
            // Each step receives its own JSON value; custom commands cannot mutate
            // previous outputs or state through an argument reference.
            return result === undefined ? null : JSON.parse(JSON.stringify(result))
        }
        const result = Object.create(null)
        for (const key of Object.keys(value)) result[key] = resolve(value[key])
        return result
    }
    const canonical = (value) => {
        if (Array.isArray(value)) return value.map(canonical)
        if (!value || typeof value !== 'object') return value
        const result = Object.create(null)
        for (const key of Object.keys(value).sort()) result[key] = canonical(value[key])
        return result
    }
    const condition = (c) => {
        if (c.op === 'all') return c.conditions.every(condition)
        if (c.op === 'any') return c.conditions.some(condition)
        if (c.op === 'not') return !condition(c.condition)
        if (c.op === 'truthy') return !!resolve(c.value)
        const left = resolve(c.left),
            right = resolve(c.right)
        if (c.op === 'eq' || c.op === 'ne') {
            const equal = JSON.stringify(canonical(left)) === JSON.stringify(canonical(right))
            return c.op === 'eq' ? equal : !equal
        }
        if (typeof left !== 'number' || typeof right !== 'number') throw Error('Numeric comparison needs two numbers')
        switch (c.op) {
            case 'gt':
                return left > right
            case 'gte':
                return left >= right
            case 'lt':
                return left < right
            case 'lte':
                return left <= right
            default:
                throw Error('Unknown condition ' + c.op)
        }
    }
    const steps = async (list) => {
        for (const step of list) {
            if (!alive()) throw Error('Workflow cancelled')
            try {
                let output = null
                switch (step.kind) {
                    case 'source': {
                        const args = resolve(step.arguments)
                        output = step.sourceByName
                            ? await __request('sources.call', {
                                  source: step.source,
                                  tool: step.tool,
                                  arguments: args || {},
                                  source_by_name: true,
                              })
                            : await host.call(step.source, step.tool, args)
                        break
                    }
                    case 'cli':
                        output = await __cliRequest(
                            step.permit,
                            resolve(step.args),
                            resolve(step.options),
                            step.cliReference
                        )
                        break
                    case 'ai':
                        output = await host.ai.run(resolve(step.options))
                        break
                    case 'agent':
                        output = await __native('agents.execute', resolve(step.options))
                        break
                    case 'notify':
                        output = await host.notifications.send(resolve(step.options))
                        break
                    case 'state': {
                        const patch = resolve(step.patch)
                        if (!patch || typeof patch !== 'object' || Array.isArray(patch))
                            throw Error('State patch must be an object')
                        if (own(patch, '__proto__')) throw Error('Reserved state key: __proto__')
                        setState(patch)
                        output = patch
                        break
                    }
                    case 'dataset': {
                        if (!['set', 'patch', 'remove', 'clear', 'rows', 'count', 'aggregate'].includes(step.operation))
                            throw Error('Unknown dataset operation')
                        output = host.data[step.operation](step.table, resolve(step.value), resolve(step.options))
                        break
                    }
                    case 'command': {
                        const fn = (__def.commands || {})[step.command]
                        if (typeof fn !== 'function') throw Error('Unknown command ' + step.command)
                        output = await fn(resolve(step.args))
                        break
                    }
                    case 'if': {
                        output = condition(step.condition)
                        await steps(output ? step.then : step.else || [])
                        break
                    }
                    default:
                        throw Error('Unknown workflow step ' + step.kind)
                }
                outputs[step.id] = output === undefined ? null : JSON.parse(JSON.stringify(output))
            } catch (error) {
                throw Error('Step ' + step.id + ': ' + String(error.message || error))
            }
        }
    }
    await steps(definition.steps)
    return outputs
}
function __runtimeActivity() {
    return JSON.stringify({
        commands: Object.keys(__def.commands || {}),
        pendingRequests: __pending.size,
        timers: Array.from(__timers, ([id, t]) => ({ id, repeat: t.repeat, delayMs: t.delay })),
    })
}
var __workflowEpoch = 0
async function __executeWorkflow(id, input) {
    const epoch = __workflowEpoch
    const run = await __native('workflows.begin', { id, input })
    const alive = () => epoch === __workflowEpoch
    let output
    try {
        output =
            run.definition.version === 2
                ? await __native('workflows.execute', { definition: run.definition, input, run: run.run })
                : await __runWorkflow({ definition: run.definition, input }, alive)
    } catch (error) {
        if (alive()) {
            try {
                await __native('workflows.finish', {
                    id,
                    run: run.run,
                    error: String(error.message || error).slice(0, 4096),
                })
            } catch (trackingError) {
                console.warn('Workflow status: ' + trackingError.message)
            }
        }
        throw error
    }
    if (!alive()) throw Error('Workflow cancelled: view reloaded')
    await __native('workflows.finish', { id, run: run.run })
    return output
}

// Native workflow bridge. Custom functions cannot hide orchestration/effects
// inside a version 2 command. The host keeps this guard active while draining
// promise jobs, then restores the live state even when a function throws.
function __workflowTransform(name, args) {
    __badgeLive = __state
    __inBadge = true
    const freeze = (value) => {
        if (!value || typeof value !== 'object') return value
        for (const key of Object.keys(value)) value[key] = freeze(value[key])
        return new Proxy(value, {
            set() {
                throw Error('Workflow transforms cannot change state')
            },
            deleteProperty() {
                throw Error('Workflow transforms cannot change state')
            },
            defineProperty() {
                throw Error('Workflow transforms cannot change state')
            },
            setPrototypeOf() {
                throw Error('Workflow transforms cannot change state')
            },
        })
    }
    __state = freeze(JSON.parse(JSON.stringify(__state)))
    const fn = (__def.commands || {})[name]
    if (typeof fn !== 'function') throw Error('Unknown workflow transform ' + name)
    if (fn.constructor && fn.constructor.name === 'AsyncFunction')
        throw Error('Version 2 workflow transforms must be synchronous')
    const value = fn(JSON.parse(args))
    if (value && typeof value.then === 'function') throw Error('Version 2 workflow transforms must be synchronous')
    return JSON.stringify(value === undefined ? null : value)
}
function __workflowPatch(patch) {
    setState(JSON.parse(patch))
}
