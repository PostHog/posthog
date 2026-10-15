# Response rates by survey design

These comparisons come from PostHog popover surveys over one week in October 2026.
Response rate is the share of people who saw a survey and answered at least one question.
Each survey counts once, so a few high-traffic surveys do not dominate.

| Design choice                         | Typical response rate | Compared with                           |
| ------------------------------------- | --------------------- | --------------------------------------- |
| Triggered by an event or action       | 7.5%                  | 2.9% for a URL condition, 2.1% for none |
| First question is a single choice     | 8.0%                  | 3.5% for a rating, 0.8% for open text   |
| Satisfaction on a 3-point emoji scale | 7.7%                  | 2.8% for a 0–10 number scale            |
| Shown on mobile                       | 13.6%                 | 3.2% on web                             |
| Centered modal                        | 12.8%                 | 2.8% in the bottom-right corner         |

The share of responders who finish every question drops to about 57% at two
questions and about 45% at three or more.

A model that holds the other choices constant keeps these effects:

- An open-text first question cuts the odds of a response to about a fifth.
- An event trigger about doubles them.
- A choice question first, partial responses on, and a targeted audience each add
  about 1.4 to 1.5 times.
- A popup delay over 15 seconds cuts them by about a quarter.

The mobile and 0–10 scale differences do not hold up once the other choices are
held constant.

## Limits

- These are correlations. Teams that set up event triggers may also write better
  surveys in other ways.
- A centered modal interrupts the user more than a corner popover. Its higher
  response rate does not measure what the interruption costs. Suggest it only
  when the user wants the most responses from a short, important question.
- API surveys depend on how each app captures `survey shown`, so their rates
  are not comparable. Hosted forms count only people who opened the link.
