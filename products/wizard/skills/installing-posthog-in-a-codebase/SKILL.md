---
name: installing-posthog-in-a-codebase
description: >-
  Install and configure a PostHog SDK in a repository you can read and edit, following PostHog's docs for
  the framework. Use when a user working in their codebase asks to add, install, or set up PostHog, product
  analytics, session replay, or a PostHog SDK. Covers finding the right docs page, installing the latest
  package, getting the project token and ingestion host from project-get, keeping them in the env file,
  server-side setup, identifying users, and verifying the change. If you can't access the user's code, as is
  common in ChatGPT on the web or Claude on the web, use installing-posthog-from-chat instead.
---

# Installing PostHog in a codebase

Use this skill when you can read and edit the user's code.
If you can't access their code, as is common in ChatGPT on the web or Claude on the web, use `installing-posthog-from-chat`.

PostHog's docs are the source of truth for each SDK's setup.
Init options, file locations and recommended settings change between SDK releases, so read the docs page for the framework before you write code, and follow it rather than what you remember.

## 1. Find the framework and read its docs

Detect the framework from the manifest files (`package.json`, `pyproject.toml`, `requirements.txt`, `Gemfile`, `composer.json`, `go.mod`, and so on) and the app's entry points.
A web app with its own backend usually needs a client SDK and a server SDK, so read both pages.

| Framework                      | Docs page                                            |
| ------------------------------ | ---------------------------------------------------- |
| JavaScript web (any framework) | https://posthog.com/docs/libraries/js.md             |
| React, including Vite apps     | https://posthog.com/docs/libraries/react.md          |
| Next.js                        | https://posthog.com/docs/libraries/next-js.md        |
| Vue.js                         | https://posthog.com/docs/libraries/vue-js.md         |
| Nuxt                           | https://posthog.com/docs/libraries/nuxt-js.md        |
| Svelte and SvelteKit           | https://posthog.com/docs/libraries/svelte.md         |
| Angular                        | https://posthog.com/docs/libraries/angular.md        |
| Astro                          | https://posthog.com/docs/libraries/astro.md          |
| Remix                          | https://posthog.com/docs/libraries/remix.md          |
| React Router                   | https://posthog.com/docs/libraries/react-router.md   |
| TanStack Start                 | https://posthog.com/docs/libraries/tanstack-start.md |
| Node.js, including Express     | https://posthog.com/docs/libraries/node.md           |
| Python, including FastAPI      | https://posthog.com/docs/libraries/python.md         |
| Django                         | https://posthog.com/docs/libraries/django.md         |
| Flask                          | https://posthog.com/docs/libraries/flask.md          |
| Ruby                           | https://posthog.com/docs/libraries/ruby.md           |
| Ruby on Rails                  | https://posthog.com/docs/libraries/ruby-on-rails.md  |
| PHP                            | https://posthog.com/docs/libraries/php.md            |
| Laravel                        | https://posthog.com/docs/libraries/laravel.md        |
| Go                             | https://posthog.com/docs/libraries/go.md             |
| Java                           | https://posthog.com/docs/libraries/java.md           |
| .NET                           | https://posthog.com/docs/libraries/dotnet.md         |
| Elixir                         | https://posthog.com/docs/libraries/elixir.md         |
| Rust                           | https://posthog.com/docs/libraries/rust.md           |
| React Native                   | https://posthog.com/docs/libraries/react-native.md   |
| Flutter                        | https://posthog.com/docs/libraries/flutter.md        |
| iOS                            | https://posthog.com/docs/libraries/ios.md            |
| Android                        | https://posthog.com/docs/libraries/android.md        |

For a framework that isn't listed, call `docs-search` with the framework name.

## 2. Install the latest SDK

Add each package with the project's own package manager and no version, for example `npm install posthog-js`, `pnpm add posthog-node`, `uv add posthog` or `bundle add posthog-ruby`.
That resolves the newest release.
Don't type a version into the manifest from memory, because that pins an old release.

In a monorepo, install into the package that runs the app, not the workspace root.

## 3. Get the token and host

Call `project-get` without an ID.
Use `api_token` as the project token and `api_host` as the SDK's host option.

- Read both from environment variables in code, using the names the docs page uses (for example `NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN` and `NEXT_PUBLIC_POSTHOG_HOST`).
- Write the real values to the env file the framework loads, such as `.env.local` or `.env`. If the project has an example env file, add the variable names there with empty values.
- Never hard-code the token or the host in source files, and never use them as fallback defaults in code.

## 4. Initialize as the docs show

- Initialize the SDK once, in the place the docs page names. Don't add a second initialization elsewhere.
- For `posthog-js`, set `defaults` to the date the docs page shows. It selects the newest set of recommended settings, so don't take a date from memory.
- For a backend SDK in a long-running server, create one client for the process, reuse it, and shut it down when the process exits. Don't create a client per request.
- In serverless or edge handlers (for example Next.js route handlers on Vercel, or AWS Lambda), the runtime can freeze as soon as the response is sent, so queued events are lost. Flush before the handler returns: await `flush()` on a reused client, or use the platform's `waitUntil`, as the docs page describes.
- For a server-rendered app (Django, Rails, Laravel and similar), add the server SDK as well as the browser snippet.

## 5. Identify users

If the app has login, call `identify` after login with a stable user ID from the auth system, such as the database ID, not an email address or display name.
Call `reset()` on logout.
Send server-side events with the same distinct ID, so client and server events land on the same person.

## 6. Verify

Run the project's build, type check or tests, and fix anything your change broke.
If you can run the app, load a page and check that events arrive with `read-data-schema` or `execute-sql`.
Tell the user which environment variables to add in their hosting provider before they deploy.
