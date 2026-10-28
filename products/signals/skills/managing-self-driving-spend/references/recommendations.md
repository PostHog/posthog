# Recommendation rules

Go through every control in [controls.md](controls.md) and decide whether it applies to this project.
A good recommendation names the specific item to change (a scanner, a signal type, a scout, an evaluation), the evidence from the queries, the monthly saving in dollars, and what the user loses.
"Reduce replay spend" is not a recommendation. "Turn off inbox findings for the 'Checkout errors' scanner: 3 of 140 settled reports resolved, saves about $40 a month" is.

Base every rule on yield from settled reports (see "Yield" in queries.md), not on reports still waiting for a fix.
Let the project's data decide what to keep. Do not assume that one signal type, scanner, or scout is always worth more than another.
Compare each item to the project's own average: a settled rate well below the project's average is low, whatever the absolute number.

Convert spend in the period to a monthly figure before you compare savings.
Skip any change that saves less than about $10 a month, unless the user asked about that item.

## What to check

- **Spend limit.** Compare the current limit with the expected monthly spend.
  If the limit is lower, put this first and say on which day of the period the limit would be reached.
  Otherwise put it last, and suggest about 1.2 times the expected monthly spend after the other changes.
  Explain that Self-driving pauses for the rest of the period when the limit is reached.
- **Parts of a large source.** For each source over 10% of signal spend, run "Breakdown inside a source".
  Recommend turning down the specific parts with a low settled rate: a scanner's inbox findings or sampling rate, an error tracking signal type, an evaluation report, an alert's investigation.
  Prefer this to turning off the whole source.
- **Whole sources.** Recommend turning off a source only when its settled rate is low and it has no setting to narrow it.
  When its yield is too new to judge, use other evidence such as how many of its reports anyone opened, and say that resolution is not known yet.
- **Scouts with no output.** Scouts that created and edited no reports in the period. Group them into one recommendation with their total spend, and name the largest ones.
- **Frequent scouts with low yield.** Scouts that run hourly or more often and have a low settled rate.
  Recommend a slower schedule before a pause, and give the saving for the new schedule.
  A scout that edits many reports keeps them current. Slow it down, do not pause it.
- **Steering.** When one kind of report inside a source has a low settled rate and no setting selects it, suggest research instructions that name it.
  Give no dollar figure.
- **Automatic pull requests.** Compare pull requests opened and merged per source.
  When a source opens many and few merge, suggest a higher priority threshold.
  Say that the saving is not measured.
- **Daily report limit.** Look at reports shown per day. Recommend a limit only when a few days hold much more than the rest, near the 75th percentile of daily reports.

## How to present them

Split the list in three parts:

1. **Recommended.** Changes with a clear case, ranked by monthly saving.
2. **Worth a look.** Changes with a real saving and a real cost, where the user has to decide. Say what decides it.
3. **Checked, no change.** Controls you looked at that need no change, each with one line on why.
   This shows the user that you went through all of them.

For each recommendation, end with "I can apply this" or with where the user changes it in the app.
