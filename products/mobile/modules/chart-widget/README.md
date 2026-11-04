# Chart widget

A home-screen widget for iOS and Android that shows a pinned insight from the Views tab and reads PostHog by itself.
See the sections below for the store contract, the fetch rules and the identifiers.

The widget shows one pin as a number and sparkline (small), one pin as a chart with its value and change (medium), or one chart plus up to two number tiles (large).
The person picks the pin in the OS: the Edit widget sheet on iOS, the configure screen on Android.
The app itself shows nothing about widgets.

## How it works

The app and the widget share a small store.
The app writes the session copy and the pin catalog; the widget writes one snapshot per pin.
The widget never runs the app's JavaScript and never refreshes the OAuth token.

```text
app: src/features/widgets/chartWidgetSync.ts
  token, account or project change ──> setCredentials ──> Keychain item (iOS), EncryptedSharedPreferences (Android)
  complete pin list read, pin display change ──> setCatalog ──> chart.catalog
  session end, demo mode ──> clearCatalog + clearCredentials (also every chart.snapshot.* key)

widget: targets/HedgehogWidget/Chart*.swift (iOS), modules/chart-widget/android/ (Android)
  picker and render ──> chart.catalog
  timer ──> credentials ──> GET insights/{id}/?refresh=force_cache ──> chart.snapshot.<pinId> or chart.snapshotError.<pinId>
```

`useChartWidgetSync()` runs in `app/_layout.tsx` next to the hedgehog sync and calls `startChartWidgetSync()`.
That function subscribes to the stores below, so auth and Views do not import the widget code:

| Trigger                                                                                    | What the app writes                                        |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Launch, after the session restores                                                         | Credentials (`launch`)                                     |
| Sign in, demo mode ends                                                                    | Credentials (`sign_in`)                                    |
| Token refresh (`onSessionTokensChanged` in `src/auth/tokens.ts`)                           | Credentials (`refresh`)                                    |
| Project switch, project rename                                                             | Credentials (`project_switch`)                             |
| A success write of the signed-in project's pin list in the query cache: a read, pin, unpin | Catalog, when the list is complete                         |
| A change of the project's pin prefs (`usePinPrefs`): mode, tile, order                     | Catalog, from the cached pin list                          |
| A project with no catalog and no cached pin list: sign in, project switch, launch          | Reads the pin list once, then the catalog                  |
| Sign out, expired session (`addSessionEndTask`), signed-out launch, demo mode starts       | Clears the catalog, the credentials and every cached chart |

Each write makes the OS reload every placed widget, so the app keeps the last JSON it wrote in memory and skips an identical write.
A clear resets that memory, so the next sign in writes again even with the same token.
Writes happen only while the auth store and the stored session name the same host and user, so a sign in never pairs one account's token with another account's project.
When the signed-in project has no catalog and no cached pin list, the sync reads the pin list itself, with the query key, fetcher (`readShortcuts` in `src/features/views/listReads.ts`) and lane that `usePins` uses.
It does that once per project per session, and only when the session has the Views scopes; a failure leaves the catalog for the next Views read.
Until the new project's catalog lands after a project switch, the widget shows "In another project".

The widget never refreshes the OAuth token.
On each return to the foreground, the app refreshes an OAuth access token with less than 24 hours left (`FOREGROUND_REFRESH_MARGIN_MS` in `src/auth/authStore.ts`), then writes the new copy, so the widget's token stays valid between app opens.

The catalog takes each pin's insight from what the Views list already read: the pin metadata cache (`viewsKeys.pinMetadata`), else the pin's Number or Chart snapshot.
For up to 30 pins without either, the sync reads `GET insights/?short_id=&basic=true&refresh=force_cache` through the list-read lane (`listRead('insights')`), one at a time, and stores the answer in the same metadata cache.
A 429, a 503, an empty budget bucket or no connection stops the reads; those pins say "Open it in Views first" until the next sync.
The sync never forces a compute.

Analytics: `mobile_widget_credentials_synced` (`reason`: `launch`, `sign_in`, `refresh` or `project_switch`) and `mobile_widget_catalog_synced` (`pin_count`, `eligible_count`) on each real write.
A widget tap opens `/views/insight/<short_id>?from=widget&family=<family>` or `/views/dashboard/<id>?from=widget&family=<family>`, which sends `mobile_view_opened` with `from: widget` and `mobile_widget_opened` (`kind`, `family`).

## Store contract

| Data                  | iOS                                                                                                                                                                                                                | Android                                                                                                                    | Writer |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- | ------ |
| Credentials           | Keychain generic password: service `com.posthog.code.mobile.chart-widget`, account `credentials`, access group `group.<app bundle id>`, `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`; data is the UTF-8 JSON | `EncryptedSharedPreferences` file `chart_widget_secure` (MasterKey AES256_GCM), key `credentials`, written with `commit()` | App    |
| Catalog               | `UserDefaults(suiteName: "group.<app bundle id>")`, key `chart.catalog`                                                                                                                                            | `SharedPreferences` file `chart_widget`, key `chart.catalog`                                                               | App    |
| Snapshot of one pin   | same suite, key `chart.snapshot.<pinId>`                                                                                                                                                                           | `chart_widget`, key `chart.snapshot.<pinId>`                                                                               | Widget |
| Last error of one pin | same suite, key `chart.snapshotError.<pinId>`                                                                                                                                                                      | `chart_widget`, key `chart.snapshotError.<pinId>`                                                                          | Widget |
| Project of one pin    | same suite, key `chart.pinProject.<pinId>` = `{ "projectId": number, "projectName": string }`                                                                                                                      | kept per widget in `chart.widget.<appWidgetId>` as `projectId`, `projectName` and `pinName`, written at configure time     | Widget |
| Widget configuration  | the widget's configuration intent, kept by WidgetKit                                                                                                                                                               | `chart_widget`, key `chart.widget.<appWidgetId>` = `{ "pinId": string, "extraPinIds": string[] }`                          | Widget |

The suite is the hedgehog widget's App Group.
An App Group id is also a keychain access group of every target in the group, so the extension reads the credentials without a keychain-sharing entitlement.
The credentials stay out of `UserDefaults` because the suite is a plain file in the group container.

### Credentials JSON

```json
{
  "version": 1,
  "host": "https://us.posthog.com",
  "projectId": 2,
  "projectName": "PostHog App",
  "accessToken": "phx_...",
  "expiresAt": 1762400000000,
  "userUuid": "..."
}
```

`host` has no trailing slash.
`expiresAt` is epoch ms, or null for a personal API key, which does not expire.
The widget treats `now > expiresAt - 60000` as expired and sends no request.

### Catalog JSON

Replaced whole on each write.
Pins are in Views order, at most 30.

```json
{
  "version": 1,
  "host": "https://us.posthog.com",
  "projectId": 2,
  "projectName": "PostHog App",
  "writtenAt": 1762400000000,
  "pins": [
    {
      "id": "<shortcut id>",
      "kind": "insight",
      "name": "Signups",
      "subtitle": "Insight",
      "insightId": 123,
      "shortId": "abc123",
      "dashboardId": null,
      "eligible": true,
      "number": true,
      "chart": true,
      "reason": null
    },
    {
      "id": "<shortcut id>",
      "kind": "dashboard",
      "name": "Product KPIs",
      "subtitle": "Product KPIs · Daily active users",
      "insightId": 456,
      "shortId": "def456",
      "dashboardId": 12,
      "eligible": true,
      "number": true,
      "chart": true,
      "reason": null
    },
    {
      "id": "<shortcut id>",
      "kind": "insight",
      "name": "Checkout funnel",
      "subtitle": "Insight",
      "insightId": 789,
      "shortId": "ghi789",
      "dashboardId": null,
      "eligible": false,
      "number": false,
      "chart": false,
      "reason": "Not a chart over time"
    }
  ]
}
```

| Field         | Meaning                                                                                                                      |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `id`          | The pin's `shortcutId` (`PinView.shortcutId`). The widget configuration stores it.                                           |
| `subtitle`    | "Insight" for an insight pin. For a dashboard pin, "<dashboard name> · <tile name>", or "Dashboard" before a tile is chosen. |
| `insightId`   | Null when the app has not read the insight. The widget then reads by `shortId`.                                              |
| `shortId`     | The insight's `short_id`: the pin's `ref`, or the chosen tile's insight. Null for a dashboard pin without a tile.            |
| `dashboardId` | The dashboard's numeric id, sent as `from_dashboard`. Null for an insight pin.                                               |
| `number`      | `capabilitiesOf(query).number` (`src/model/adapters/insightSnapshot.ts`): one series or a big number, without a breakdown.   |
| `chart`       | `capabilitiesOf(query).chart`: a line or bar trends chart over time.                                                         |
| `eligible`    | A `TrendsQuery` with `number` or `chart`. iOS leaves other pins out of the picker; Android shows them grayed with `reason`.  |
| `reason`      | Null when eligible, else one of the reasons below.                                                                           |

| Reason                            | When                                                                                                      |
| --------------------------------- | --------------------------------------------------------------------------------------------------------- |
| "Choose a tile in Views first"    | A dashboard pin without a tile chosen on this phone (`PinDisplay.insightId`).                             |
| "Open it in Views first"          | The app has not read the insight yet.                                                                     |
| "Couldn't find this insight"      | The server no longer returns the insight, or it is deleted.                                               |
| "Not supported on the widget yet" | A SQL insight (`HogQLQuery`).                                                                             |
| "Not a chart over time"           | Any other kind, or a trends insight that is neither a number nor a line or bar chart (`tileLimitReason`). |

### Snapshot JSON

Written by the widget after a good read, the same shape on both platforms.
The widget renders from it when a later read fails.
The age it shows is from `lastRefreshAt` (when the server computed the numbers), else `fetchedAt`; with several pins on screen, the oldest.

```json
{
  "version": 1,
  "pinId": "...",
  "fetchedAt": 1762400000000,
  "lastRefreshAt": "2026-11-04T17:00:00Z",
  "rangeLabel": "Last 14 days",
  "intervalLabel": "day",
  "valueText": "1,284",
  "deltaPercent": 12.3,
  "deltaText": "12%",
  "deltaBasis": "vs. previous 14 days",
  "series": [{ "label": "Signups", "points": [{ "at": "2026-10-22", "value": 72 }], "previous": false }],
  "chartKind": "line"
}
```

The error record is `{ "at": <epoch ms>, "kind": "network" | "auth" | "not_found" | "rate_limited" | "bad_data" | "no_result" }`.

### Reads

`{host}/api/projects/{projectId}/insights/{insightId}/?refresh=force_cache`, plus `&from_dashboard={dashboardId}` for a dashboard pin.
Without `insightId`: `insights/?short_id={shortId}&refresh=force_cache`, taking the result whose `short_id` matches.
Headers: `Authorization: Bearer {accessToken}`, `Accept: application/json`, `User-Agent: posthog-mobile-widget/<app version> (<ios|android>)`.
Timeout 20 s.
The widget only reads what the server already computed: never `blocking`, never `force_blocking`.

| Answer                               | Error kind     | Render                                                              |
| ------------------------------------ | -------------- | ------------------------------------------------------------------- |
| 200 with `result` and no query error | none (cleared) | The new snapshot                                                    |
| 401, 403, or an expired token        | `auth`         | "Open PostHog to update"                                            |
| 404                                  | `not_found`    | "<name> was unpinned or deleted." and how to pick another pin       |
| 429, 503                             | `rate_limited` | The cached snapshot                                                 |
| No connection                        | `network`      | The cached snapshot                                                 |
| A response the parser cannot read    | `bad_data`     | The cached snapshot, else the error                                 |
| 200 with `result: null`, no error    | `no_result`    | The cached snapshot, else "Open it in PostHog to load this insight" |

### Cadence

- iOS: the timeline reloads after 30 minutes, with entries at +0 and +15 minutes so the age text stays true. Only the first entry fetches.
- Android: `updatePeriodMillis` 1800000, and a one-time WorkManager request (network connected) on each update and configuration change.
- Both: one request per distinct pin per refresh, shared by every widget that shows it.
- Every render shows the age of its data, "Updated 12 min ago", in orange past 60 minutes.

### States

| State                      | Text                                                                                                                           |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Not configured             | "Choose a pin", then "Touch and hold to pick a pin from your Views tab"                                                        |
| No credentials, demo mode  | "Sign in to see your pins", then "Open PostHog to sign in"                                                                     |
| Expired or rejected token  | "Open PostHog to update"                                                                                                       |
| Pin missing from catalog   | "<name> is no longer pinned"                                                                                                   |
| Catalog of another project | "In another project", then "Switch to <projectName> in PostHog"                                                                |
| Pin from another project   | iOS: a pin missing from the catalog whose `chart.pinProject` marker names another project. Same text, with that project's name |
| Ineligible pin             | The pin's `reason`                                                                                                             |
| First read pending         | The title, "Loading…" and a placeholder sparkline. Only for a pin never read                                                   |
| No cached result           | The title, then "Open it in PostHog to load this insight"; links to the insight                                                |

A state links to `<scheme>://views`; a chart links to the pin's view with `from=widget` (see "How it works").
The scheme is `posthog`, `posthog-dev` or `posthog-preview` by build variant (`src/lib/appVariants.json`).

### Identifiers

|               | iOS                                                                     | Android                                                                |
| ------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Widget        | kind `ChartWidget`, in the `HedgehogWidget` extension target            | see "Chart widget (Android)"                                           |
| Native module | `ChartWidget`, pod `PostHogChartWidget` (`ios/ChartWidgetModule.swift`) | `ChartWidget`, class `com.posthog.code.mobile.chart.ChartWidgetModule` |
| App Group     | `group.<app bundle id>`, shared with the hedgehog widget                | n/a                                                                    |

The pod is not named `ChartWidget`, because the extension target owns the widget's Swift module names and a pod of the same name would shadow them.

## Native module API

```ts
// Imported by path: local Expo modules have no node_modules entry.
import { isAvailable, setCredentials, clearCredentials, setCatalog, clearCatalog, reloadWidgets } from '../../../modules/chart-widget'

isAvailable(): boolean // false on web and in a build without the native module
setCredentials(credentials: WidgetCredentials): void // store the session copy, then refresh every placed widget; throws when the store write fails
clearCredentials(): void // remove the session copy and every chart.snapshot.*, chart.snapshotError.* and chart.pinProject.* key, then refresh
setCatalog(json: string): void // replace chart.catalog, then refresh
clearCatalog(): void // remove chart.catalog, then refresh
reloadWidgets(): void // refresh every placed Chart widget
```

App code calls `syncWidgetCredentials`, `syncWidgetCatalog` and `clearWidgetState` in `src/features/widgets/chartWidgetSync.ts` instead of the module, so the writes stay idempotent.
`buildCatalog` (`src/features/widgets/chartWidgetCatalog.ts`) is the pure catalog builder.

## Chart widget (Android)

RemoteViews only (no Glance, no Compose), API 24 and up. Code in `android/src/main/java/com/posthog/code/mobile/chart/`:

| File                                 | Role                                                                                                                       |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------- |
| `ChartModels.kt`                     | Credentials, catalog, widget config, snapshot and error JSON (`org.json`).                                                 |
| `ChartStore.kt`                      | The two preferences files below. Every write uses `commit()`.                                                              |
| `TrendsParser.kt`                    | Insight response to snapshot: mirrors `insightSnapshot.ts`, `insightFormatting.ts`, `snapshotChart.ts`, `rangePresets.ts`. |
| `ChartFetcher.kt`                    | One `HttpURLConnection` read per pin, `refresh=force_cache`, 20 s timeouts, status to error kind.                          |
| `ChartWidgetRefresh.kt`              | `refreshAll(context)`: render from the cache now, then queue one network pass.                                             |
| `ChartRefreshWorker.kt`              | The `WorkManager` pass: each distinct pin once, then a render of every widget.                                             |
| `ChartRenderer.kt`, `ChartCanvas.kt` | Layout choice, states, text, deep links; the chart drawn on a `Canvas` into a `Bitmap`.                                    |
| `ChartWidgetProvider.kt`             | The `AppWidgetProvider`. Every callback is wrapped, because a receiver exception kills the app process.                    |
| `ChartWidgetConfigureActivity.kt`    | "Choose a pin", a plain `Activity` built from views.                                                                       |

### Identifiers

|                    | Android                                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider           | receiver `com.posthog.code.mobile.chart.ChartWidgetProvider`, info `res/xml/chart_widget_info.xml`                                                                              |
| Configure activity | `com.posthog.code.mobile.chart.ChartWidgetConfigureActivity` (`APPWIDGET_CONFIGURE`, exported)                                                                                  |
| Plain preferences  | `chart_widget`: `chart.catalog`, `chart.snapshot.<pinId>`, `chart.snapshotError.<pinId>`, `chart.widget.<appWidgetId>`                                                          |
| Secure preferences | `chart_widget_secure` (`EncryptedSharedPreferences`, `MasterKey` AES256_GCM): `credentials`                                                                                     |
| Work               | unique `chart-widget-refresh` (REPLACE, network required), `chart-widget-keep-enabled`                                                                                          |
| Deep links         | `<scheme>://views/insight/<shortId>?from=widget&family=<small\|medium\|large>`, `<scheme>://views/dashboard/<dashboardId>?from=widget&family=…`, states open `<scheme>://views` |

The scheme comes from the package suffix (`.dev`, `.preview`, none), the same table as `src/lib/appVariants.json`.
`chart.widget.<appWidgetId>` also keeps `projectId`, `projectName` and `pinName` from the moment the pin was chosen.
They let the widget say "In another project" after a project switch and name a pin that left the catalog.
An Android snapshot also carries `inProgress`: the last bucket is still open, so the chart dashes its last segment and dims its last bar.
A corrupt or restored keystore file is deleted and counts as signed out; the app writes the session again on its next token change or launch.

### Cadence

- `updatePeriodMillis` is 30 minutes. Each `onUpdate`, each module call and each configure Done calls `refreshAll`.
- `refreshAll` renders every placed widget from the cache on the calling thread, then queues the unique network pass.
  It queues nothing when no widget is placed or the token is missing or expired; the widget then shows its state.
- The pass reads each distinct pin of every placed widget once, writes the snapshot (which clears its error) or the error, then renders all widgets.
  A rejected token stops the pass and marks the remaining pins `auth`. A new token from the app clears every `auth` error.
- WorkManager disables its reschedule receiver when no work is pending, and that component change makes the system send `APPWIDGET_UPDATE` again.
  A no-op job 10 years out (`chart-widget-keep-enabled`) stays queued while a widget is placed, so that loop cannot start. `onDisabled` cancels both.
- The age text is computed at each render, from `lastRefreshAt` (when the server computed the numbers) or else `fetchedAt`.

### Layout and theme

- Family from the launcher's portrait size: small when the width is under 250 dp or the height under 110 dp, large from 300 dp high, else medium.
  A resize re-renders that widget (`onAppWidgetOptionsChanged`).
- Text is `TextView`s, so it follows the user's font size. The chart bitmap is sized for the room the text leaves, capped at 1.5 MB.
- The chart is drawn twice, light and dark. `@integer/chart_widget_{light,dark}_visibility` (in `values` and `values-night`) shows the one that matches the launcher's night mode, so a theme change needs no redraw.
  Colors come from `res/values{,-night}/colors.xml`. From Android 12, runtime text colors use `RemoteViews.setColorInt` with both themes.

### Configure flow

1. Placing a Chart widget opens "Choose a pin". It starts with `RESULT_CANCELED`, so backing out does not place the widget.
2. Eligible pins are radio rows (name and the catalog `subtitle`). Ineligible pins follow, grayed, under "Can't show on the widget" with their `reason`.
3. "Also show (large widget)" offers checkboxes for up to two more eligible pins, never the chosen one.
4. Done writes `chart.widget.<id>`, calls `refreshAll`, and returns `RESULT_OK` with the widget id.
5. Signed out: "Sign in to PostHog to see your pins". No pins: "Pin a dashboard or insight in Views first". Both offer "Open PostHog".
6. `widgetFeatures="reconfigurable"` lets Android 12+ reopen the screen from a long press; it preselects the current choice.

## Chart widget (iOS)

The iOS widget is a second kind in the `HedgehogWidget` extension (`targets/HedgehogWidget/`).
It reads the catalog and its snapshots from the App Group suite and the credentials from the keychain, and it reads PostHog itself.

| File                          | What it holds                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `AppGroup.swift`              | The App Group id from the extension's bundle id, shared with the hedgehog's `SharedStore`                                            |
| `ChartModels.swift`           | `Codable` shapes of the credentials, catalog, snapshot and snapshot error JSON                                                       |
| `ChartStore.swift`            | Store keys, snapshot, error and pin project reads and writes, the keychain read (Foundation + Security)                              |
| `ChartFetcher.swift`          | The cache-only insight read, status mapping, and `ChartRefresh` (one request per pin at a time)                                      |
| `TrendsParser.swift`          | `TrendsQuery` response to snapshot, mirroring `insightSnapshot.ts`, `insightFormatting.ts`, `snapshotChart.ts` and `rangePresets.ts` |
| `ChartState.swift`            | Which state each slot shows, which pins a refresh reads, deep links, age text, gallery sample data                                   |
| `ChartWidgetIntent.swift`     | `ChartWidgetIntent`, `PinEntity` and `PinQuery` (the Edit widget picker)                                                             |
| `ChartTimelineProvider.swift` | `AppIntentTimelineProvider`: reads, writes snapshots, builds entries                                                                 |
| `ChartViews.swift`            | SwiftUI for small, medium and large, light and dark                                                                                  |
| `ChartWidget.swift`           | The `AppIntentConfiguration`, registered in `HedgehogWidgetBundle.swift`                                                             |

### Native check

From `products/mobile` on macOS:

```sh
swiftc targets/HedgehogWidget/{AppGroup,ChartModels,ChartStore,ChartFetcher,TrendsParser,ChartState}.swift scripts/check_chart_widget.swift -o /tmp/check-chart
/tmp/check-chart
```

It prints one line per check and exits non-zero on a failure.
It covers a big number with a compare aggregate, a 14-day line with compare totals, bars with an open last bucket, two and six series, breakdown placeholders, every value format, range labels, the catalog picker filter, fetch URLs, headers and status mapping, the store round trip, pin project markers, and every widget state.
The SwiftUI, WidgetKit and AppIntents files do not compile there; `xcodebuild` checks them.

### Identifiers

|               | iOS                                                                                                                                                                               |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Widget        | kind `ChartWidget`, target `HedgehogWidget`, families small, medium, large                                                                                                        |
| Configuration | `ChartWidgetIntent` ("Chart"): `pin: PinEntity?`, `extraPins: [PinEntity]?` (large only)                                                                                          |
| Picker entity | `PinEntity`, id = the catalog pin id; `PinQuery` lists eligible pins in Views order                                                                                               |
| Store         | `UserDefaults(suiteName: "group.<app bundle id>")`, keys `chart.catalog`, `chart.snapshot.<pinId>`, `chart.snapshotError.<pinId>`, `chart.pinProject.<pinId>`                     |
| Credentials   | keychain generic password, service `com.posthog.code.mobile.chart-widget`, account `credentials`, access group `group.<app bundle id>`                                            |
| Deep links    | `<scheme>://views/insight/<shortId>?from=widget&family=<small\|medium\|large>`, `<scheme>://views/dashboard/<dashboardId>?from=widget&family=...`; states open `<scheme>://views` |

The scheme follows the bundle id's variant suffix, as in `src/lib/appVariants.json`: `posthog`, `posthog-dev` or `posthog-preview`.

### Timeline

- Each timeline call reads the configured pins (the primary pin, plus up to two extra pins on large), each distinct pin once, concurrently.
- A pin is read again only when its snapshot is 5 minutes old, it has an error, or the catalog was written after the snapshot (a new tile).
  Widgets that show the same pin share the read; a second widget in the same process waits for the running one.
- After a 429 or 503, the pin waits a minute before the next read.
- Each timeline call writes `chart.pinProject.<pinId>` for every configured pin the catalog lists, when it changed.
  A configured pin that later leaves the catalog shows "In another project" when its marker names a project other than the token's, else "<name> is no longer pinned".
- A 200 with `result: null` writes `no_result`: the server has not computed the insight, and the widget never asks it to.
  With a cached snapshot the widget keeps showing it; without one it asks to open the insight, which links to it.
- Entries at now and now + 15 minutes, which only move the age label. Reload policy `.after(now + 30 min)`.
- An expired token (`now > expiresAt - 60 s`), a missing token or a catalog of another project sends no request.
- The gallery shows sample numbers; a placed widget's snapshot shows the store without a read.

### Snapshot fields

- `valueText` follows `numberParts`: `aggregated_value`; else the window total with a compare series and summable math; else the last complete bucket.
  It is absent when the insight has no single number (several series or a breakdown).
- `deltaPercent` is the signed change behind the pill: a percent, or points for a `percentage` or `percentage_scaled` insight.
  `deltaText` has no sign or arrow: "12%" (whole above 10, one decimal below), "0.7 pts", or "No change".
  A change against zero has no pill.
- `deltaBasis` follows `deltaBasisText`: "vs previous period", or "vs Nov 2" against the bucket before.
- `series` holds up to five current series, then the previous-period series of those, aligned to the first current series and cut to the last 60 buckets.
  A bucket without a number has `value: null`.
- The age label reads `lastRefreshAt` (when the server computed the numbers), else `fetchedAt`.
  With several pins on screen it shows the oldest. It turns orange after 60 minutes.
