# Exporting devices from other platforms

Each platform stores the same three facts under different names: the device token, the platform, and the user ID your app gave it.
APIs and export screens change, so check the platform's current docs before relying on a field name.

| Platform               | Where the devices are                                                          | Token field                                                    | User ID field                                                |
| ---------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------- | ------------------------------------------------------------ |
| OneSignal              | `POST /players/csv_export` (CSV of subscriptions), or the dashboard CSV export | `identifier` (push rows only)                                  | `external_user_id`, which you must request in `extra_fields` |
| Braze                  | `POST /users/export/ids` or a segment export                                   | `push_tokens[].token`, with `push_tokens[].platform` and `app` | `external_id`                                                |
| Customer.io            | People → Export to CSV → Export other → All devices in this workspace          | the device `id`                                                | the person's `id`                                            |
| Airship                | `GET /api/channels` (paged), or `GET /api/named_users`                         | `push_address`                                                 | `named_user_id`                                              |
| Firebase (own backend) | Your own database. FCM has no API that lists tokens                            | the token your app saved                                       | the user ID saved next to it                                 |

## Notes per platform

- **OneSignal**: email and SMS subscriptions come out in the same export. Keep the push rows only. Drop unsubscribed rows: `invalid_identifier` is `t`, or `notification_types` is negative. These rows can still carry a token, and an imported token can be sent to again. Also drop rows with a null token. `device_type` tells iOS from Android.
- **Braze**: a profile can hold several tokens for several apps. Keep the ones for this app and platform. An anonymous profile has no `external_id` and cannot be mapped.
- **Customer.io**: devices are listed per person, with a platform. A person identified only by email in Customer.io needs that email mapped to the distinct ID the app identifies with.
- **Airship**: a channel with a null `push_address` or no `named_user_id` cannot be imported. `device_type` is `ios` or `android`.
- **Firebase**: tokens go stale when an app is reinstalled. Prefer tokens your backend saw recently. FCM tokens go to the `firebase` channel even for iOS devices.

## Expo

Expo tokens (`ExponentPushToken[...]`) cannot be imported anywhere. They only work through Expo's push service. The app has to read the native token with `getDevicePushTokenAsync` and register it through the PostHog SDK, which happens as people open the updated app.
