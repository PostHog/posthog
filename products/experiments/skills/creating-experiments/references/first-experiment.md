# First experiment: definitions and best practices

Use this file when "New to experiments?" in SKILL.md says the user is new.
Tell them the definitions and best practices below before your first question, or before you create the draft if you ask none.
Keep the wording plain and the list this short. Leave out a term the user already uses correctly, and tie a practice to their test when the request makes that easy.
Don't add a question or wait for a reply. Carry on with the normal flow.

## Definitions

- Variant and control: each variant is one version of what you're testing. The control is the version people see today, and the test variant is the change.
- Exposure: the point where someone is counted in the experiment, by default when your code checks the feature flag for them. Only people who were exposed count in the results.
- Bucketing: how PostHog assigns people to variants. The split is random, and the same ID always gets the same variant, so a person keeps theirs as long as their ID stays the same.
- Device ID: an ID for the browser or device someone uses. It doesn't change when they sign in, so bucketing on it keeps their variant through sign-in, but not across devices.
- Minimum detectable effect: the smallest change in your metric that the experiment is sized to detect. A smaller effect needs more people, so the experiment runs longer.

## Best practices

1. Before you launch, write one hypothesis and pick one primary metric to judge it by.
2. Work out the sample size and running time before you launch, so you know when to read the results.
3. Change one thing at a time, so you know what caused the difference.
4. Don't stop early because the results look good. Results move a lot in the first few days, so run it for the planned time.
5. Finish properly: record a conclusion, ship a variant, and remove the feature flag from your code.
