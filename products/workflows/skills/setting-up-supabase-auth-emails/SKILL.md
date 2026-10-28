---
name: setting-up-supabase-auth-emails
description: 'Connect a Supabase project so its auth emails send through PostHog email templates via the Supabase Send Email Hook, in an order that never breaks a sign-up. Use when asked to set up, connect, test, or fix Supabase auth emails, Supabase email templates, or the Supabase Send Email Hook, or when Supabase shows "email rate limit exceeded" or an auth email error.'
---

# Setting up Supabase auth emails

Supabase calls PostHog's Send Email Hook for each auth email. The user does the Supabase steps by hand, so tell them exactly what to click, and keep the order below.

If the Supabase MCP server is connected, use it to read the project URL (step 3) and the logs (when a hook call fails). It has no tools for Auth settings. Leave the hook and the rate limit to the user even if you have other Supabase access, because those settings send every sign-up email.

The tools are behind a beta flag. If `supabase-auth-emails-settings-get` isn't available, tell the user the feature isn't enabled for their project yet and stop.

## The setup

1. **Read the current state.** Call `supabase-auth-emails-settings-get`. Keep the `hook_url`, the `email_types` list and the current `templates` mapping. If the project is already set up, change only what the user asked for.
2. **Check the email sender.** The templates need an email channel with a verified sending domain. Follow the setup check in the `building-workflows` skill's onboarding reference.
3. **Get the project URL.** With the Supabase MCP, call `get_project_url`. Otherwise it is `https://<project-ref>.supabase.co`. The project ref is the id in the user's Supabase dashboard URL, `supabase.com/dashboard/project/<project-ref>`. For a self-hosted project or a custom domain, ask the user for the URL their app uses to reach Supabase Auth.
4. **Have the user create the hook in Supabase, switched off.** While the hook is on, any hook failure fails the user's sign-up or password reset. Give them the `hook_url` and these steps:
   - Open **Authentication** > **Hooks**, add a **Send Email** hook, and choose **HTTPS**.
   - Paste the hook URL as the endpoint.
   - Click **Generate secret** and copy the whole value.
   - Leave **Enable Send Email hook** off, and save.
5. **Save the connection and map the templates.** Never invent a hook secret, and don't repeat it back in your reply. If a secret is already stored, leave `hook_secret` out to keep it. Never send it blank, because a blank value clears it. Ask before you replace a stored secret. Pick one way:
   - **Starter templates.** Call `supabase-auth-emails-settings-update` with `supabase_url` and the `hook_secret` the user pastes. Then call `supabase-auth-emails-starter-templates-create`. It creates and maps a template for each email type with `has_starter_template` that has no usable one yet. If it fails for want of a verified sender, go back to step 2. To change a template's copy or styling, use the `designing-email-templates` skill.
   - **Existing templates.** Send `supabase_url`, `hook_secret` and `templates` in one `supabase-auth-emails-settings-update` call. Build `templates` from the step 1 mapping with your changes merged in, because the field replaces the whole mapping. Ask before you unmap a template that already sends.
6. **Check before the hook goes live.** In the response of your last call, confirm `supabase_url` is set, `has_hook_secret` is true, and every core email type in the `email_types` list from step 1 has a template. The write responses leave that list out. Core types are the ones that don't end in `_notification`. A core type with no template fails the user's action. A notification with no template is skipped.
7. **Have the user turn the hook on.** In Supabase, edit the Send Email hook, switch on **Enable Send Email hook**, and save. PostHog can't see whether the hook is on, so the **Connected** status on the Supabase card only means the connection is saved.
8. **Have the user raise Supabase's email rate limit.** Supabase checks its own hourly email limit before it calls PostHog. The built-in mailer allows 2 per hour. Once the hook sends the emails, the user can raise the limit under **Authentication** > **Rate Limits**. Ask them to check the value there.
9. **Test it.** Ask the user to invite a user (**Authentication** > **Users** > **Add user** > **Send invitation**) or request a password reset, to an address they can read. The email should arrive from the mapped template.

Report done only after the user confirms a test email arrived. Name any email type you left without a template.

To disconnect, the user turns the hook off in Supabase first, then clicks **Disconnect** in the PostHog setup window. In the other order, every auth email fails in between.

## When a hook call fails

The user sees these in Supabase, in the app's error or under **Logs** > **Auth**. With the Supabase MCP, find the failed call yourself with its `query_logs` tool before you ask the user. That tool reads Supabase's logs. PostHog's `query-logs` tool can't see them.

| What Supabase shows                                        | Cause                                                                                                                                                  | Fix                                                                                               |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| "email rate limit exceeded"                                | Supabase's own hourly limit. PostHog never got the call.                                                                                               | Raise the limit (step 8).                                                                         |
| Supabase's generic hook error, with a 401 from the hook    | The hook secret doesn't match.                                                                                                                         | Have the user copy the full secret again and save it with `supabase-auth-emails-settings-update`. |
| "No PostHog template is set for the ... email."            | A core email type has no template.                                                                                                                     | Map one (step 5).                                                                                 |
| "We couldn't send your email. Try again in a few minutes." | No project URL saved, a mapped template that is deleted or no longer transactional and sensitive, no verified sender, the email quota, or a slow send. | Check the settings and each mapped template. If they are fine, retry.                             |
| Links in the email go to the wrong place                   | The project URL is wrong.                                                                                                                              | Save the right URL.                                                                               |
