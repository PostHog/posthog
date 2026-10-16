# Response rates by survey design

These comparisons come from PostHog popover surveys over one week in October 2026.
Response rate is the share of people who saw a survey and answered at least one question.
Each survey counts once, so a few high-traffic surveys do not dominate.

| Design choice                     | Typical response rate | Compared with                                     |
| --------------------------------- | --------------------- | ------------------------------------------------- |
| Triggered by an event or action   | 7.5%                  | 2.9% for a URL condition, 2.1% for none           |
| First question is a single choice | 8.0%                  | 3.5% for a rating, 0.8% for open text             |
| Shown on mobile                   | 13.6%                 | 3.2% on web                                       |
| Middle-center modal               | 12.8%                 | 2.8% for the default bottom-right (`right`) popup |

The share of responders who finish every question is about 57% for two questions
and about 45% for three or more. The number of questions does not change how
many people start.

A model that holds the other choices constant keeps these effects:

- An open-text first question cuts the odds of a response to about a fifth.
- An event trigger about doubles them.
- A centered modal (`middle_center` or `center`) raises them about 1.8 times.
- A choice question first and a targeted audience each raise them about 1.4 to
  1.5 times.
- A popup delay over 15 seconds cuts them by about a quarter.

The mobile difference, the 0–10 rating scale, and the number of questions do not
hold up once the other choices are held constant.

## Limits

- These are correlations. Teams that set up event triggers may also write better
  surveys in other ways.
- With partial responses off, a person counts only after finishing every question,
  so surveys with partial responses on look better partly because of how they
  count. Turn it on to keep first answers, not to raise the rate.
- A centered modal interrupts the user more than a corner popover. Its higher
  response rate does not measure what the interruption costs. Suggest it only
  when the user wants the most responses from a short, important question.
- API surveys depend on how each app captures `survey shown`, so their rates
  are not comparable. Hosted forms count only people who opened the link.
