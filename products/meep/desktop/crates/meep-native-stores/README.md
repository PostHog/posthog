# meep-native-stores

Read Calendar and Reminders through EventKit, Contacts through the Contacts framework, and Mail through its read-only Apple Events adapters. Copy this directory as a path dependency. Select just the stores your application uses.

```toml
meep-native-stores = { path = "../meep-native-stores", default-features = false, features = ["calendar"] }
```

| Cargo feature | Reader | Operations |
| --- | --- | --- |
| `calendar` | `calendar::EventKit`, `calendar::EventKitReminders` | List calendars and reminder lists, query events in a time range, fetch reminders by list and completion |
| `contacts` | `contacts::ContactStore` | Look up a contact by ID or collect matches up to a limit |
| `mail` | `mail::MailApp` | Read mailboxes, pages of message summaries and individual messages from the open Mail app |

Each reader has a trait for alternative implementations and fixtures. Perform reads off the UI thread. The host checks the caller's grant, bounds the query and chooses which fields to return. For Calendar, Reminders and Contacts, read `Privacy::access` and call `Privacy::request` from a user action. For Mail use `automation(false)` for status and `automation(true)` for a user-initiated request. Reads check the existing OS decision. A read with undecided access returns an error.

Package the real adapter in the application's Mac bundle. Its Info.plist needs a usage description for each enabled store. EventKit uses `NSCalendarsFullAccessUsageDescription` and `NSRemindersFullAccessUsageDescription` on macOS 14 and later. Include `NSCalendarsUsageDescription` and `NSRemindersUsageDescription` when supporting older systems. Contacts uses `NSContactsUsageDescription` and Mail uses `NSAppleEventsUsageDescription`. For hardened runtime builds using these facilities, configure the corresponding Calendar, Address Book and Apple Events entitlements.

Run `cargo run --example agenda` for the fixture calendar. Mail's tests run against simulated mailboxes and messages.
