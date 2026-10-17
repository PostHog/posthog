# Over-the-air updates

EAS Update ships JavaScript and asset changes to installed builds without a store release.
Native changes still need a new build, see [RELEASING.md](RELEASING.md).

## How a device gets an update

- `expo-updates` checks `https://u.expo.dev/4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` each time the app starts.
- A new update downloads in the background. The app runs it on the next cold start.
- So a tester sees an update after two launches: the first downloads it, the second runs it.
- Development builds load JavaScript from Metro and ignore updates.

## Channels

Each build profile in `eas.json` sets a channel, and the build listens to that channel for life.
Each channel points at the EAS branch with the same name.

| Profile | Channel | Branch | Publish with |
| --- | --- | --- | --- |
| `development` | `development` | `development` | Not used. Development builds load from Metro. |
| `preview` | `preview` | `preview` | `pnpm update:preview` |
| `production` | `production` | `production` | `pnpm update:production` |

Both update scripts pass `--environment`, so the bundle gets the same `EXPO_PUBLIC_*` values as the builds on that channel.
Expo SDK 55 and later require it.

The `env` block of a build profile in `eas.json` applies to builds only, not to `eas update`.
So the update scripts set the same values themselves: `APP_VARIANT` on both, and `EXPO_PUBLIC_SIGNUP_LINK=0` on production.
If you run `eas update` by hand, set them the same way.
The app reads its variant from its bundle id first, so an update with the wrong `APP_VARIANT` cannot make a store build look internal, but the sign-up link follows the update.

Do not run `pnpm update`. That is pnpm's own command, and it upgrades dependencies.

## Runtime version

`app.config.ts` sets `runtimeVersion.policy` to `appVersion`, so the runtime version equals `version` (now `1.2.0`).
An update reaches only the builds with the same runtime version.

The policy does not detect native changes. You must raise `version` when a change needs native code, for example:

- a new or upgraded package with native code (most `expo-*` and `react-native-*` packages),
- a new or changed config plugin, or a change to `ios`, `android` or `plugins` in `app.config.ts`,
- an Expo SDK upgrade.

Then make new builds. If you publish such a change as an update to the old runtime version, the app can crash on start.
If you are not sure, check whether `npx expo prebuild --clean` produces a different `ios/` or `android/` folder.

## Ship a JavaScript-only fix

1. Commit the fix. `--auto` uses the last commit message as the update message.
2. Publish to preview and test it on a preview build (open the app, close it, open it again):

   ```sh
   cd products/mobile
   pnpm update:preview
   ```

3. Publish the same commit to production:

   ```sh
   pnpm update:production
   ```

   To limit the risk, start with part of the users and raise it later:

   ```sh
   pnpm update:production --rollout-percentage 10
   eas update:edit <update group id> --rollout-percentage 100    # when the update looks healthy
   ```

## Roll back

Find the last good update group on the branch, then publish it again as the newest update:

```sh
eas update:list --branch production
eas update:republish --group <update group id>
```

To send devices back to the JavaScript inside their build, use `eas update:roll-back-to-embedded --branch production`.
`eas update:rollback` asks which of the two you want.

A rollback reaches each device on its next two launches, the same as an update.

## See what a device runs

Settings shows the app version in every build.
Development and preview builds also show an Environment group: the build variant, the update channel, the update (the first 8 characters of `Updates.updateId` and the time of `Updates.createdAt`, or "Built in" when the app runs the JavaScript inside the build), and the API host kind.
Store builds do not show the channel or update.
The app's own analytics events carry `app_variant`, `update_channel`, `api_host_kind`, `data_mode` (`demo` or `live`, null until the demo flag loads) and `project_id` (null when signed out) as super properties.
On the EAS project page, the Updates tab lists each update group with its runtime version, platforms and commit message.
