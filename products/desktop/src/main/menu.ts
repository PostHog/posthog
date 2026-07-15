import { app, Menu, type MenuItemConstructorOptions, shell } from 'electron'

export interface MenuActions {
    showShell: () => void
}

export function buildAppMenu(actions: MenuActions): void {
    const isMac = process.platform === 'darwin'

    const template: MenuItemConstructorOptions[] = [
        ...(isMac ? [{ role: 'appMenu' } as MenuItemConstructorOptions] : []),
        {
            label: 'File',
            submenu: [
                {
                    label: 'Settings',
                    accelerator: 'CmdOrCtrl+,',
                    click: () => actions.showShell(),
                },
                { type: 'separator' },
                isMac ? { role: 'close' } : { role: 'quit' },
            ],
        },
        { role: 'editMenu' },
        {
            label: 'View',
            submenu: [
                { role: 'reload' },
                { role: 'forceReload' },
                { role: 'toggleDevTools' },
                { type: 'separator' },
                { role: 'resetZoom' },
                { role: 'zoomIn' },
                { role: 'zoomOut' },
                { type: 'separator' },
                { role: 'togglefullscreen' },
            ],
        },
        { role: 'windowMenu' },
        {
            role: 'help',
            submenu: [
                {
                    label: 'PostHog docs',
                    click: () => void shell.openExternal('https://posthog.com/docs'),
                },
                {
                    label: `Version ${app.getVersion()}`,
                    enabled: false,
                },
            ],
        },
    ]

    Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}
