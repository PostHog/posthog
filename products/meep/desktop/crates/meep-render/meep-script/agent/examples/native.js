// A self-contained native SDK test view. Nothing writes to another app on load.
const LAB = 'native-lab:'
const TABS = ['Alerts', 'Time', 'Inputs', 'Apps']
let countdownTimer = null
let refreshing = false
const inFlight = new Set()
const stamp = () => 'lab:' + Date.now()
function logResult(title, detail, failed = false) {
    setState((s) => ({
        message: title,
        detail: String(detail || ''),
        failed,
        history: [{ title, detail: String(detail || '').slice(0, 500), failed, at: Date.now() }, ...s.history].slice(
            0,
            12
        ),
    }))
}
async function run(name, work, id = name) {
    if (inFlight.has(id)) return
    inFlight.add(id)
    let shown = false
    const timer = setTimeout(() => {
        shown = true
        setState((s) => ({ pending: [...s.pending, { id, name }] }))
    }, 150)
    try {
        await work()
    } catch (error) {
        logResult(name + ' failed', error.message || error, true)
    } finally {
        clearTimeout(timer)
        inFlight.delete(id)
        if (shown) setState((s) => ({ pending: s.pending.filter((action) => action.id !== id) }))
    }
}
async function refresh() {
    if (refreshing) return
    refreshing = true
    try {
        const inventory = await host.permissions()
        const reminders = await host.reminders.list()
        const jobs = await host.background.list()
        let authorization
        try {
            authorization = (await host.notifications.authorization()).status
        } catch (_) {
            authorization = 'unavailable'
        }
        setState({ grants: inventory.access?.native || [], reminders, jobs, authorization })
    } finally {
        refreshing = false
    }
}
async function permission(capability) {
    const inventory = await host.permissions()
    if ((inventory.access?.native || []).includes(capability)) return true
    const reasons = {
        notifications: 'Send test notifications and reminders from Native Lab.',
        background: 'Run a scheduled test command while this view is closed.',
        'clipboard.read': 'Read the clipboard when you press Read clipboard.',
        'clipboard.paste': 'Paste your test text into the app you choose.',
        'selection.read': 'Read selected text from the app you choose.',
        'apps.open': 'Open the app link you enter in Native Lab.',
        'calendar.read': 'Show the events in your next seven days.',
        'calendar.write': 'Create the test event shown in this form.',
        'reminders.read': 'Show your next reminders.',
        'reminders.write': 'Create the test Apple Reminder shown in this form.',
        'contacts.read': 'Find the contacts matching the name you search for.',
        'mail.read': 'Show the subjects of your newest mail.',
    }
    const allowed = await host.request({ kind: 'native', capability, reason: reasons[capability] })
    await refresh()
    if (!allowed) logResult('Access wasn’t granted', 'You can enable it later in View settings.')
    return allowed
}
async function enableNotifications() {
    if (!(await permission('notifications'))) return false
    let authorization = await host.notifications.authorization()
    if (authorization.status === 'notDetermined') authorization = await host.notifications.requestAuthorization()
    setState({ authorization: authorization.status })
    if (!['authorized', 'provisional'].includes(authorization.status)) {
        logResult('Notifications are off', 'Enable View in macOS System Settings → Notifications, then refresh.', true)
        return false
    }
    return true
}
function content(s) {
    return {
        title: s.longText
            ? 'A longer notification title — Café, 日本語, and a reminder worth following up on'
            : s.title,
        body: s.longText
            ? 'This is a longer message to check wrapping and keep the action reachable. '.repeat(8)
            : s.body,
        delivery: s.delivery,
        sound: s.sound ? 'default' : 'none',
        action: { label: 'Open Native Lab', command: 'acknowledge', args: { origin: 'notification' } },
    }
}
async function sendNotification() {
    const s = getState()
    if (s.delivery === 'inApp' ? !(await permission('notifications')) : !(await enableNotifications())) return
    const result = await host.notifications.send({ ...content(s), id: LAB + 'notification' })
    if (result.system && !result.system.submitted) throw Error(result.system.error)
    logResult(
        s.delivery === 'inApp' ? 'In-app notification sent' : 'Submitted to macOS',
        'Focus and your system settings control when banners and sounds appear.'
    )
}
async function showToast(style) {
    const s = getState()
    await host.toast.show({
        id: LAB + 'toast',
        title: style === 'progress' ? 'Running a test…' : content(s).title,
        body: content(s).body,
        style,
        action: { label: 'Test action', command: 'acknowledge', args: { origin: 'toast' } },
    })
    logResult(
        'Toast shown',
        style === 'progress'
            ? 'Use Finish progress to update this toast.'
            : 'It dismisses after six seconds, or when you close it.'
    )
}
function localDate(value) {
    const d = new Date(value)
    const z = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}
function clockTime(value) {
    const d = new Date(value)
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}
function readableTime(value) {
    const d = new Date(value)
    if (!Number.isFinite(d.getTime())) return 'No date'
    return `${d.getDate()} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()]} · ${clockTime(value)}`
}
function scheduleFrom(s) {
    if (s.scheduleKind === 'after') return { kind: 'after', delayMs: Number(s.seconds) * 1000 }
    if (s.scheduleKind === 'interval') return { kind: 'interval', everyMs: Number(s.minutes) * 60000 }
    if (s.scheduleKind === 'at') {
        const date = new Date(`${s.date}T${s.time}:00`)
        if (!Number.isFinite(date.getTime())) throw Error('Choose a valid date and time.')
        return { kind: 'at', at: date.toISOString() }
    }
    if (s.scheduleKind === 'cron') return { kind: 'cron', expression: s.cron, timezone: s.timezone }
    const schedule = { kind: 'calendar', frequency: s.frequency, time: s.time, timezone: s.timezone }
    if (s.frequency === 'weekly')
        schedule.days = s.days
            .split(',')
            .map((d) => d.trim())
            .filter(Boolean)
    if (s.frequency === 'monthly') schedule.dayOfMonth = Number(s.dayOfMonth)
    return schedule
}
async function scheduleTest(background, delayMs) {
    const s = getState()
    const schedule = delayMs === undefined ? scheduleFrom(s) : { kind: 'after', delayMs }
    if (s.delivery === 'inApp' ? !(await permission('notifications')) : !(await enableNotifications())) return
    if (background && !(await permission('background'))) return
    const id = stamp()
    if (background) await host.background.register({ id, schedule, command: 'background_ping', args: content(s) })
    else await host.reminders.schedule({ ...content(s), id, schedule })
    await refresh()
    logResult(
        background ? 'Background test scheduled' : 'Notification reminder scheduled',
        'Your app will notify you when it is due. Closing this view does not cancel it.'
    )
}
function stopCountdown() {
    if (countdownTimer !== null) clearInterval(countdownTimer)
    countdownTimer = null
    setState({ countdown: 0 })
}
function startCountdown() {
    stopCountdown()
    const until = Date.now() + 5000
    setState({ countdown: 5 })
    countdownTimer = setInterval(() => {
        const left = Math.max(0, Math.ceil((until - Date.now()) / 1000))
        setState({ countdown: left })
        if (!left) {
            stopCountdown()
            logResult('Timeout completed', 'This five-second timer belongs to the running view.')
        }
    }, 200)
}
function button(label, id, fn, primary = false) {
    return Button(label, {
        id,
        variant: primary ? 'primary' : 'secondary',
        disabled: getState().pending.some((action) => action.id === id),
        onClick: () => run(label, fn, id),
    })
}
function buttons(...children) {
    return Row({ gap: 8, wrap: true, shrink: false }, ...children)
}
function field(label, id, key, hint) {
    return Field(
        { label, for: id, hint },
        Input({ id, label, value: String(getState()[key]), onChange: (value) => setState({ [key]: value }) })
    )
}
function section(title, detail, ...children) {
    return Column({ gap: 12, shrink: false }, Section(title, detail), ...children)
}
function alerts(s) {
    return Column(
        { gap: 24, shrink: false },
        section(
            'System notifications',
            'Send a real macOS notification, or compare it with in-app feedback.',
            Row(
                { wrap: true, gap: 8 },
                Badge(
                    {
                        authorized: 'Enabled in macOS',
                        provisional: 'Quiet notifications',
                        denied: 'Off in macOS',
                        notDetermined: 'Not enabled',
                        unavailable: 'Unavailable in this build',
                    }[s.authorization] || 'Checking…'
                ),
                button('Enable notifications', 'enable-notifications', enableNotifications)
            ),
            Form(
                { id: 'notification-form', gap: 16 },
                field('Title', 'notification-title', 'title'),
                Field(
                    { label: 'Message', for: 'notification-body' },
                    Textarea({
                        id: 'notification-body',
                        label: 'Notification message',
                        rows: 2,
                        value: s.body,
                        onChange: (body) => setState({ body }),
                    })
                ),
                Field(
                    { label: 'Delivery', for: 'delivery' },
                    Select({
                        id: 'delivery',
                        label: 'Notification delivery',
                        value: s.delivery,
                        options: [
                            { value: 'system', label: 'macOS notification' },
                            { value: 'inApp', label: 'In-app notification' },
                            { value: 'both', label: 'Both' },
                        ],
                        onChange: (delivery) => setState({ delivery }),
                    })
                ),
                Toggle({ label: 'Play a sound', checked: s.sound, onChange: (sound) => setState({ sound }) }),
                buttons(
                    button('Send notification', 'send-notification', sendNotification, true),
                    button('Dismiss test notification', 'dismiss-notification', async () => {
                        await host.notifications.dismiss(LAB + 'notification')
                        logResult('Notification dismissed')
                    })
                )
            )
        ),
        Divider(),
        section(
            'In-app feedback',
            'Toasts share an ID, so updates replace the existing message.',
            buttons(
                ...['info', 'success', 'error', 'progress'].map((style) =>
                    button(style[0].toUpperCase() + style.slice(1), 'toast-' + style, () => showToast(style))
                )
            ),
            buttons(
                button('Finish progress', 'finish-progress', async () => {
                    await host.toast.update({
                        id: LAB + 'toast',
                        title: 'Test completed',
                        body: 'The progress message was updated in place.',
                        style: 'success',
                    })
                    logResult('Progress updated')
                }),
                button('Dismiss toast', 'dismiss-toast', () => host.toast.dismiss(LAB + 'toast'))
            ),
            Toggle({
                label: 'Use long text and Unicode',
                checked: s.longText,
                onChange: (longText) => setState({ longText }),
            })
        )
    )
}
function scheduleRow(entry) {
    const background = entry.kind === 'background'
    const detail = entry.enabled
        ? 'Next: ' + readableTime(entry.nextRun)
        : entry.lastRun
          ? 'Last run: ' + readableTime(entry.lastRun)
          : 'Paused'
    return Column(
        { id: 'schedule-' + entry.id, gap: 6, pb: 14, pt: 14, border: 'bottom', shrink: false },
        Row(
            { gap: 8, wrap: true },
            Text(entry.payload.title || entry.payload.args?.title || 'Background test', { weight: 'medium' }),
            Badge(entry.status)
        ),
        Caption((background ? 'Background command' : 'Reminder') + ' · ' + detail),
        entry.lastError && Text(entry.lastError, { color: 'danger', size: 12 }),
        buttons(
            !background &&
                button('Snooze 10s', 'snooze-' + entry.id, async () => {
                    await host.reminders.snooze(entry.id, 10000)
                    await refresh()
                }),
            background &&
                button(entry.enabled ? 'Pause' : 'Resume', 'pause-' + entry.id, async () => {
                    await host.background.setEnabled(entry.id, !entry.enabled)
                    await refresh()
                }),
            button('Remove', 'remove-' + entry.id, async () => {
                if (background) await host.background.unregister(entry.id)
                else await host.reminders.cancel(entry.id)
                await refresh()
            })
        )
    )
}
function timeTests(s) {
    const entries = [...s.reminders, ...s.jobs].sort((a, b) => b.nextRun.localeCompare(a.nextRun))
    return Column(
        { gap: 24, shrink: false },
        section(
            'Remind me later',
            'Your app sends a notification when the time is up. Nothing is added to Calendar or Apple Reminders.',
            buttons(
                button('Remind me in one hour', 'remind-one-hour', () => scheduleTest(false, 3600000), true),
                button('Test in 10 seconds', 'remind-ten-seconds', () => scheduleTest(false, 10000))
            ),
            Caption(
                'Uses the message and delivery selected in Alerts. View’s background service must be running; overdue reminders arrive when your Mac wakes.'
            )
        ),
        Divider(),
        section(
            'Custom schedules',
            'Choose a delay, an exact time, or a repeating schedule.',
            Form(
                { id: 'schedule-form', gap: 16 },
                Field(
                    { label: 'Schedule', for: 'schedule-kind' },
                    Select({
                        id: 'schedule-kind',
                        label: 'Schedule type',
                        value: s.scheduleKind,
                        options: [
                            { value: 'after', label: 'After a delay' },
                            { value: 'at', label: 'At a date and time' },
                            { value: 'interval', label: 'At an interval' },
                            { value: 'calendar', label: 'Daily, weekly, or monthly' },
                            { value: 'cron', label: 'Cron expression' },
                        ],
                        onChange: (scheduleKind) => setState({ scheduleKind }),
                    })
                ),
                s.scheduleKind === 'after' && field('Delay in seconds', 'delay-seconds', 'seconds', 'Try 10 seconds.'),
                s.scheduleKind === 'interval' &&
                    field(
                        'Interval in minutes',
                        'interval-minutes',
                        'minutes',
                        'At least one minute; missed runs coalesce.'
                    ),
                s.scheduleKind === 'at' &&
                    Field(
                        { label: 'Date', for: 'schedule-date', hint: 'Uses this Mac’s local time.' },
                        DatePicker({ id: 'schedule-date', value: s.date, onChange: (date) => setState({ date }) })
                    ),
                ['at', 'calendar'].includes(s.scheduleKind) &&
                    Field(
                        { label: 'Time', for: 'schedule-time' },
                        TimePicker({ id: 'schedule-time', value: s.time, onChange: (time) => setState({ time }) })
                    ),
                s.scheduleKind === 'calendar' &&
                    Field(
                        { label: 'Repeat', for: 'frequency' },
                        Select({
                            id: 'frequency',
                            label: 'Recurrence',
                            value: s.frequency,
                            options: ['daily', 'weekly', 'monthly'],
                            onChange: (frequency) => setState({ frequency }),
                        })
                    ),
                s.scheduleKind === 'calendar' &&
                    s.frequency === 'weekly' &&
                    field('Days', 'weekdays', 'days', 'Comma-separated: mon,tue,wed,thu,fri'),
                s.scheduleKind === 'calendar' &&
                    s.frequency === 'monthly' &&
                    field('Day of month', 'month-day', 'dayOfMonth', 'Months without this date are skipped.'),
                s.scheduleKind === 'cron' &&
                    field('Cron expression', 'cron-expression', 'cron', 'Minute · hour · day · month · weekday'),
                ['calendar', 'cron'].includes(s.scheduleKind) &&
                    field('Time zone', 'schedule-timezone', 'timezone', 'An IANA name, such as Europe/Madrid.'),
                buttons(
                    button('Schedule notification', 'schedule-reminder', () => scheduleTest(false), true),
                    button('Schedule background test', 'schedule-background', () => scheduleTest(true))
                ),
                Caption('Uses the title, message, and delivery selected in Alerts.')
            )
        ),
        Divider(),
        section(
            'Scheduled work',
            entries.length ? 'Only work belonging to Native Lab appears here.' : 'No scheduled work yet.',
            ...entries.slice(0, 12).map(scheduleRow),
            entries.length > 12 && Caption('Showing the latest 12. View settings lists all schedules.'),
            buttons(button('Refresh schedules', 'refresh-schedules', refresh))
        ),
        Divider(),
        section(
            'View timer',
            'A local timeout stops when its script is unloaded.',
            Text(s.countdown ? s.countdown + ' seconds remaining' : 'Ready for a five-second timer', {
                weight: 'medium',
            }),
            buttons(
                button('Start timer', 'start-timer', startCountdown),
                button('Cancel timer', 'cancel-timer', stopCountdown)
            )
        )
    )
}
function inputs(s) {
    const items = [
        { id: 'copy', label: 'Copy test text', shortcut: 'cmd-shift-c' },
        { id: 'reset', label: 'Reset sample inputs' },
        { id: 'disabled', label: 'Unavailable action', disabled: true },
    ]
    const menuAction = (id) => {
        if (id === 'copy') host.copy(s.testText)
        else setState({ testText: 'Hello from Native Lab', choice: 'first', checked: false })
        logResult('Menu action', id)
    }
    return Column(
        { gap: 24, shrink: false },
        section(
            'Native controls',
            'Check focus, keyboard navigation, date selection, and menu behavior.',
            Form(
                { id: 'controls-form', gap: 16 },
                field('Test text', 'test-text', 'testText'),
                Field(
                    { label: 'Date', for: 'sample-date' },
                    DatePicker({ id: 'sample-date', value: s.date, onChange: (date) => setState({ date }) })
                ),
                Field(
                    { label: 'Time', for: 'sample-time' },
                    TimePicker({ id: 'sample-time', value: s.time, onChange: (time) => setState({ time }) })
                ),
                Field(
                    { label: 'Date and time', for: 'sample-datetime' },
                    DatePicker({
                        id: 'sample-datetime',
                        value: s.dateTime,
                        withTime: true,
                        onChange: (dateTime) => setState({ dateTime }),
                    })
                ),
                Checkbox({
                    label: 'Sample checkbox',
                    checked: s.checked,
                    onChange: (checked) => setState({ checked }),
                }),
                Toggle({ label: 'Sample switch', checked: s.switched, onChange: (switched) => setState({ switched }) }),
                Input({
                    id: 'invalid-example',
                    label: 'Validation example',
                    value: '',
                    placeholder: 'An invalid field',
                    invalid: true,
                }),
                Caption('The empty field above intentionally demonstrates validation styling.'),
                buttons(
                    ActionMenu({ id: 'sample-actions', label: 'Actions', items, onAction: menuAction }),
                    button('Show confirmation', 'confirm-dialog', async () => {
                        const accepted = await host.confirm({
                            title: 'Run a test confirmation?',
                            message: 'This only records your choice in Native Lab.',
                            confirmLabel: 'Confirm',
                        })
                        logResult(accepted ? 'Confirmed' : 'Cancelled', 'The native dialog returned ' + accepted + '.')
                    })
                )
            ),
            ContextMenu(
                { id: 'sample-context', items, onAction: menuAction },
                Box(
                    { p: 16, bg: 'inset', radius: 6 },
                    Text('Right-click here', { weight: 'medium' }),
                    Caption('The context menu shares the same actions and shortcuts.')
                )
            )
        )
    )
}
function apps(s) {
    return Column(
        { gap: 24, shrink: false },
        section(
            'Files',
            'Choose a UTF-8 text file to inspect, list a folder you choose (read-only), or export a small test document.',
            buttons(
                button('Choose text file', 'pick-file', async () => {
                    const files = await host.files.pick({
                        title: 'Choose a test text file',
                        extensions: ['txt', 'md', 'json', 'js'],
                    })
                    if (!files?.length) {
                        logResult('File selection cancelled')
                        return
                    }
                    try {
                        const body = await host.files.readText(files[0].id)
                        logResult(
                            'Read ' + files[0].name,
                            body.length + ' characters. File contents are not saved in this view.'
                        )
                    } finally {
                        await host.files.release(files[0].id)
                    }
                }),
                button('Choose folder', 'pick-folder', async () => {
                    const folder = await host.files.pickFolder({ title: 'Choose a folder to list' })
                    if (!folder) {
                        logResult('Folder selection cancelled')
                        return
                    }
                    try {
                        const page = await host.files.list(folder.id, { limit: 20 })
                        logResult(
                            'Listed ' + folder.name,
                            page.entries
                                .map(
                                    (e) =>
                                        (e.kind === 'folder' ? '▸ ' : '') +
                                        e.path +
                                        (e.downloaded === false ? ' (in the cloud)' : '')
                                )
                                .join('\n') || 'Empty folder'
                        )
                    } finally {
                        await host.files.release(folder.id)
                    }
                }),
                button('Export test text', 'save-file', async () => {
                    const result = await host.files.saveText({ name: 'Native Lab.txt', text: s.testText + '\n' })
                    logResult(result ? 'File exported' : 'Export cancelled')
                })
            )
        ),
        Divider(),
        section(
            'Clipboard and selection',
            'For paste or selection, you have three seconds to switch to the target app.',
            Form({ id: 'clipboard-form', gap: 16 }, field('Test text', 'clipboard-text', 'testText')),
            buttons(
                button('Copy test text', 'copy-text', () => {
                    host.copy(s.testText)
                    logResult('Copied to clipboard')
                }),
                button('Read clipboard', 'read-clipboard', async () => {
                    if (!(await permission('clipboard.read'))) return
                    const text = await host.clipboard.readText()
                    logResult('Clipboard read', text.length + ' characters. Contents are not saved in this view.')
                })
            ),
            buttons(
                button('Paste in 3 seconds', 'paste-text', async () => {
                    if (!(await permission('clipboard.paste'))) return
                    logResult('Switch to the target app', 'Pasting in three seconds…')
                    await host.clipboard.paste(s.testText, { delayMs: 3000 })
                    logResult('Paste requested', 'The test text was sent to the frontmost app.')
                }),
                button('Read selection in 3 seconds', 'read-selection', async () => {
                    if (!(await permission('selection.read'))) return
                    logResult('Switch to the target app', 'Reading selected text in three seconds…')
                    const text = await host.selection.readText({ delayMs: 3000 })
                    logResult('Selection read', text.length + ' characters. Contents are not saved in this view.')
                })
            )
        ),
        Divider(),
        section(
            'App links',
            'Open the URL with its registered application.',
            Form(
                { id: 'app-link-form', gap: 16 },
                field('URL', 'app-url', 'url'),
                buttons(
                    button('Open link', 'open-link', async () => {
                        if (await permission('apps.open')) {
                            await host.apps.open(s.url)
                            logResult('Link opened')
                        }
                    })
                )
            )
        ),
        Divider(),
        section(
            'Calendar',
            'Reads every calendar on this Mac, including accounts added in System Settings → Internet Accounts. Creating adds a real event; delete it there when you’re finished.',
            buttons(
                button('Show next 7 days', 'read-events', async () => {
                    if (!(await permission('calendar.read'))) return
                    const start = new Date()
                    const events = await host.calendar.events({
                        start: start.toISOString(),
                        end: new Date(+start + 7 * 86400000).toISOString(),
                        limit: 20,
                    })
                    logResult(
                        events.length
                            ? `${events.length} upcoming event${events.length === 1 ? '' : 's'}`
                            : 'No events in the next 7 days',
                        events
                            .map(
                                (e) =>
                                    `${e.allDay ? new Date(e.start).toLocaleDateString() : new Date(e.start).toLocaleString()} · ${e.title} (${e.calendar})`
                            )
                            .join('\n')
                    )
                })
            ),
            Form(
                { id: 'calendar-form', gap: 16 },
                field('Event title', 'event-title', 'eventTitle'),
                field(
                    'Calendar name',
                    'event-calendar',
                    'calendarName',
                    'Leave blank to use the first available calendar.'
                ),
                field('Start', 'event-start', 'eventStart', 'ISO date and time with an offset.'),
                field('End', 'event-end', 'eventEnd'),
                buttons(
                    button('Create test event', 'create-event', async () => {
                        if (!(await permission('calendar.write'))) return
                        const result = await host.calendar.create({
                            title: s.eventTitle,
                            start: s.eventStart,
                            end: s.eventEnd,
                            ...(s.calendarName ? { calendar: s.calendarName } : {}),
                        })
                        logResult('Calendar event created', result.id)
                    })
                )
            )
        ),
        Divider(),
        section(
            'Apple Reminders integration',
            'Optional: reads and creates items in Apple’s separate Reminders app. For a notification later, use the Time tab.',
            buttons(
                button('Show next reminders', 'read-reminders', async () => {
                    if (!(await permission('reminders.read'))) return
                    const items = await host.systemReminders.items({ limit: 10 })
                    logResult(
                        items.length
                            ? `${items.length} open reminder${items.length === 1 ? '' : 's'}`
                            : 'No open reminders',
                        items
                            .map(
                                (r) =>
                                    `${r.due ? (r.dueAllDay ? new Date(r.due).toLocaleDateString() : new Date(r.due).toLocaleString()) : 'No date'} · ${r.title} (${r.list})`
                            )
                            .join('\n')
                    )
                })
            ),
            Form(
                { id: 'apple-reminder-form', gap: 16 },
                field('Reminder title', 'apple-title', 'appleTitle'),
                field('List name', 'apple-list', 'listName', 'Leave blank to use your default list.'),
                buttons(
                    button('Create test reminder', 'create-apple-reminder', async () => {
                        if (!(await permission('reminders.write'))) return
                        const result = await host.systemReminders.create({
                            title: s.appleTitle,
                            notes: 'Created by Native Lab. Safe to delete after testing.',
                            ...(s.listName ? { list: s.listName } : {}),
                        })
                        logResult('Apple Reminder created', result.id)
                    })
                )
            )
        ),
        Divider(),
        section(
            'Contacts',
            'Finds people by name, organization or email, a few at a time. Nothing is saved in this view.',
            Form(
                { id: 'contacts-form', gap: 16 },
                field('Name or email', 'contact-query', 'contactQuery'),
                buttons(
                    button('Find contacts', 'find-contacts', async () => {
                        if (!(await permission('contacts.read'))) return
                        const people = await host.contacts.search({ query: s.contactQuery, limit: 5 })
                        logResult(
                            people.length
                                ? `${people.length} contact${people.length === 1 ? '' : 's'} found`
                                : 'No matching contacts',
                            people
                                .map(
                                    (p) =>
                                        `${p.name || p.organization || 'No name'}${p.emails[0] ? ' · ' + p.emails[0].value : ''}`
                                )
                                .join('\n')
                        )
                    })
                )
            )
        ),
        Divider(),
        section(
            'Mail',
            'Reads your newest messages through the Mail app, which must be open. Read-only; message text is shown as text.',
            buttons(
                button('Show newest mail', 'read-mail', async () => {
                    if (!(await permission('mail.read'))) return
                    const page = await host.mail.messages({ limit: 5 })
                    logResult(
                        page.length ? `${page.length} newest message${page.length === 1 ? '' : 's'}` : 'No messages',
                        page
                            .map(
                                (m) =>
                                    `${m.read ? '' : '● '}${m.from?.name || m.from?.email || 'Unknown'} · ${m.subject || 'No subject'}`
                            )
                            .join('\n')
                    )
                })
            )
        )
    )
}
view({
    state: () => {
        const start = Date.now() + 3600000
        return {
            tab: 0,
            pending: [],
            title: 'Hello from Native Lab',
            body: 'A native notification from your View app.',
            delivery: 'system',
            sound: true,
            longText: false,
            message: 'Ready to test',
            detail: 'Choose a capability above. Permissions are requested when needed.',
            failed: false,
            history: [],
            grants: [],
            authorization: '',
            reminders: [],
            jobs: [],
            scheduleKind: 'after',
            seconds: '10',
            minutes: '1',
            frequency: 'daily',
            days: 'mon,tue,wed,thu,fri',
            dayOfMonth: '1',
            timezone: 'Europe/Madrid',
            cron: '0 9 * * 1-5',
            date: localDate(start),
            time: clockTime(start),
            dateTime: localDate(start) + 'T' + clockTime(start),
            countdown: 0,
            testText: 'Hello from Native Lab',
            checked: false,
            switched: false,
            choice: 'first',
            url: 'https://github.com',
            eventTitle: 'Native Lab test',
            calendarName: '',
            eventStart: new Date(start).toISOString(),
            eventEnd: new Date(start + 1800000).toISOString(),
            appleTitle: 'Native Lab test',
            listName: '',
            contactQuery: '',
        }
    },
    async init() {
        setState({ pending: [], countdown: 0 })
        try {
            await refresh()
        } catch (error) {
            logResult('Could not refresh', error.message, true)
        }
        setInterval(() => {
            if (getState().tab === 1) refresh().catch(() => {})
        }, 3000)
    },
    render(s) {
        return Page(
            { gap: 12 },
            Header(
                { title: 'Native Lab', subtitle: 'Try the native capabilities available to your views.', pb: 8 },
                IconButton('refresh-cw', {
                    id: 'refresh-lab',
                    label: 'Refresh status',
                    disabled: s.pending.some((action) => action.id === 'refresh-lab'),
                    onClick: () => run('Refresh', refresh, 'refresh-lab'),
                })
            ),
            Tabs({
                id: 'lab-tabs',
                items: TABS,
                selected: s.tab,
                underline: true,
                onChange: (tab) => setState({ tab }),
            }),
            Scroll(
                { id: 'lab-content-' + s.tab, gap: 24, pt: 12 },
                Column({ w: 'full', maxW: 640, gap: 24, shrink: false }, [alerts, timeTests, inputs, apps][s.tab](s))
            ),
            Box(
                { id: 'lab-result', border: 'top', pt: 12, gap: 2, shrink: false },
                Text(s.pending.length ? s.pending[0].name + '…' : s.message, {
                    weight: 'medium',
                    size: 12,
                    color: s.failed ? 'danger' : 'ink',
                }),
                s.detail && Text(s.detail, { size: 11.5, color: s.failed ? 'danger' : 'secondary', truncate: true })
            )
        )
    },
    commands: {
        peek: () => getState(),
        select_tab: ({ tab }) => {
            if (!Number.isInteger(tab) || tab < 0 || tab >= TABS.length) throw Error('Unknown tab')
            setState({ tab })
        },
        acknowledge: (args) =>
            logResult('Action received', 'Opened Native Lab from ' + (args?.origin || 'a notification') + '.'),
        toast: ({ style = 'success' } = {}) => run('Show toast', () => showToast(style)),
        finish_progress: () =>
            run('Finish progress', () =>
                host.toast.update({ id: LAB + 'toast', title: 'Test completed', style: 'success' })
            ),
        dismiss_toast: () => host.toast.dismiss(LAB + 'toast'),
        start_timer: startCountdown,
        cancel_timer: stopCountdown,
        refresh: () => run('Refresh', refresh),
        remind: ({ delayMs = 10000 } = {}) => run('Schedule reminder', () => scheduleTest(false, delayMs)),
        async background_ping(args) {
            const result = await host.notifications.send({ ...args, id: LAB + 'background' })
            if (result.system && !result.system.submitted) throw Error(result.system.error)
        },
    },
})
