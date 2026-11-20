/**
 * How many pin slots the pill draws after Views. Home, Inbox, Chats and Views fill the pill on a 375pt phone, so the cap
 * is 0: the slot and every pin item are hidden, and a saved list loads as empty while it stays on the device. The store
 * keeps a list, so a larger cap needs no change to the saved format.
 */
export const MAX_NAV_PINS = 0

/** False while the cap is 0, which hides every "Pin to navigation" and "Unpin from navigation" item. */
export const NAV_PINS_ENABLED = MAX_NAV_PINS > 0
