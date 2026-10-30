---
name: importing-push-tokens
description: 'Move existing mobile push devices from another platform (OneSignal, Braze, Customer.io, Airship, or your own Firebase backend) into a PostHog workflows push channel, so people who installed the app before the switch still get push notifications. Covers exporting device tokens and user IDs, mapping the old user ID to the PostHog distinct ID, checking the pairing with a dry run, and importing in batches. Use when asked to import, migrate, or backfill push tokens, device tokens, FCM tokens, APNs tokens, or push subscribers.'
---

# Importing push tokens from another platform

A push notification reaches a device only when PostHog knows that device's token and which person it belongs to.
The mobile SDK registers new devices by itself. Devices that installed the app before the switch stay unknown until their token is imported.

The import pairs each **device token** with a **distinct ID**.
The distinct ID has to be the ID the app passes to `identify`, so the device lands on the person a workflow targets.
A pairing that is off by one prefix or uses another platform's internal ID imports fine but never receives a push. Getting the pairing right is most of the job.

## The tools

- `integrations-list`: find the push channel. `kind` is `apns` for iOS and `firebase` for Android (and for iOS apps that send through FCM).
- `integrations-push-tokens-create`: import up to 1000 rows per call, with `dry_run` to check without storing anything.

The same import is in the app under Workflows → Channels → **Import devices**, for a person who has a CSV.

## Which token goes to which channel

| Channel kind | Token it takes                     | Looks like                                                           |
| ------------ | ---------------------------------- | -------------------------------------------------------------------- |
| `apns`       | The APNs device token, hex encoded | 64 hex characters, for example `9f2c…e1a0`                           |
| `firebase`   | The FCM registration token         | Around 150 characters of letters, digits, `-`, `_`, often with a `:` |

- Expo tokens (`ExponentPushToken[...]`) can't be imported. They address Expo's own push service, not Apple or Google. Ask for the native APNs or FCM token instead: Expo apps can read it with `getDevicePushTokenAsync`, so the app has to start sending it to PostHog first.
- An iOS app that sends through Firebase has FCM tokens, so those go to the `firebase` channel, not `apns`.
- A row with the wrong kind of token fails as `token_mismatch`. The check rejects only shapes that cannot work, so passing it does not prove the token is live.

## Workflow

1. **Find the channel.** Call `integrations-list` and pick the `apns` or `firebase` entry for the app. If there is none, the push channel has to be set up first.
2. **Export devices from the old platform.** You need, for each device: its token, its platform, and the old platform's user ID. See [references/exporting-devices.md](references/exporting-devices.md).
3. **Map the user ID to the PostHog distinct ID.** Usually the old platform's external ID is the same value the app passes to PostHog's `identify`. Confirm it with the user, because some apps prefix IDs or identify by email in one tool and by database ID in the other. Drop devices with no user ID: an anonymous device has no person to land on.
4. **Dry run a sample.** Send 50 to 100 rows with `dry_run: true`. Read `failed`:
   - Many `unknown_person` rows mean the mapping is wrong. Stop and fix the mapping. Don't switch on `create_missing_persons` to make them pass, because that creates people nobody's app identifies.
   - `token_mismatch` rows are on the wrong channel or are Expo tokens. Split iOS and Android rows, and drop Expo tokens.
5. **Dry run everything, then import.** Send the whole set with `dry_run: true` in batches of 1000, then again without it. Keep to 60 calls per minute per project. On HTTP 429, wait a minute and send the same batch again.
6. **Handle what is left.** `not_stored` and `person_processing_disabled` rows were not saved by ingestion. Send `not_stored` rows again later. Use `create_missing_persons: true` only for `unknown_person` rows the user confirms are real people who haven't opened the new app yet.
7. **Check one person.** Look up one imported person and confirm they have a `$device_push_subscription_<app>:<hash>` property. A test push from a workflow to that person is the real proof.

Importing the same row twice stores it once, so a batch can be sent again safely.
Each stored device is one event, so a large import counts toward event usage.
