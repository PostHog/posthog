// PROTOTYPE, never merged: PostHog/michaelr-context#421. Variant B: the saved-view menu the app already uses in
// Customer Analytics, Logs and Conversations, placed at the start of the list's toolbar.
import { IconChevronDown, IconGlobe, IconPencil, IconPlus, IconUser } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { SavedView } from './viewsPrototypeStore'

export function ViewMenu({
    views,
    current,
    defaultLabel,
    onSelect,
    onCreate,
    onEdit,
    onDelete,
}: {
    views: SavedView[]
    current: SavedView | null
    defaultLabel: string
    onSelect: (id: string | null) => void
    onCreate: () => void
    onEdit: (view: SavedView) => void
    onDelete: (view: SavedView) => void
}): JSX.Element {
    const items: LemonMenuItems = [
        { items: [{ label: defaultLabel, active: !current, onClick: () => onSelect(null) }] },
        views.length
            ? {
                  title: 'Saved views',
                  items: views.map((view) => ({
                      label: view.name,
                      icon: view.visibility === 'private' ? <IconUser /> : <IconGlobe />,
                      active: current?.id === view.id,
                      onClick: () => onSelect(view.id),
                      sideAction: {
                          icon: <IconPencil />,
                          tooltip: 'Manage view',
                          dropdown: {
                              overlay: (
                                  <>
                                      <LemonButton size="small" fullWidth onClick={() => onEdit(view)}>
                                          Edit
                                      </LemonButton>
                                      <LemonButton
                                          size="small"
                                          fullWidth
                                          status="danger"
                                          onClick={() => onDelete(view)}
                                      >
                                          Delete
                                      </LemonButton>
                                  </>
                              ),
                          },
                      },
                  })),
              }
            : null,
        { items: [{ label: 'Save as new view...', icon: <IconPlus />, onClick: onCreate }] },
    ]
    return (
        <LemonMenu items={items} closeOnClickInside>
            <LemonButton
                size="small"
                type="secondary"
                sideIcon={<IconChevronDown />}
                icon={current ? current.visibility === 'private' ? <IconUser /> : <IconGlobe /> : undefined}
                data-attr="messaging-prototype-view-menu"
            >
                {current?.name ?? defaultLabel}
            </LemonButton>
        </LemonMenu>
    )
}
