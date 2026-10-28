# Recommendation rules

Rank recommendations by expected savings in dollars.
Each rule names the evidence to show the user.
Check yield before you recommend cutting anything: a source that costs a lot and produces fixes the team acts on is worth its spend.

- **Expensive source with low yield.** One source type takes over 20% of signal spend, and most of its reports are dismissed or never get a pull request.
  First narrow it at the source: error tracking signal types, replay scanners, evaluation reports, or Linear teams.
  Then add steering instructions.
  Turn the source off only when neither helps.
- **High cost per report.** One source costs much more per report than the others.
  Look at a few of its reports. Recommend a change only if they are not worth the cost.
- **Scout that rarely produces anything.** A scout takes over 10% of scout spend, and over 90% of its runs create or edit no reports.
  Run it less often first. Pause it only if it still produces nothing.
- **Spiky days.** A few days hold most of the spend.
  Find the source or scout behind each spike.
  If the spikes are noise, suggest a daily report limit near the 75th percentile of daily reports.
- **Automatic pull requests.** Many pull requests open and few merge.
  Raise the priority threshold or turn off PR generation.
  Say that the saving is not measured, because this spend is not visible yet.
- **Spend limit, always last.** Suggest a limit at about 1.2 times the expected monthly spend after the other changes.
  Explain that Self-driving pauses for the rest of the period when the limit is reached.
