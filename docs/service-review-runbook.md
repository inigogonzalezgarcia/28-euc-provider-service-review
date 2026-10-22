# The monthly service review, step by step

The meeting where the customer and the provider look at last month together. Forty-five minutes if the pack is ready; two hours if it is not.

## The week before

1. Export the month's tickets plus everything still open (`scripts/Export-JiraTickets.ps1`, or a list export from your tool) into `data/tickets.csv`.
2. Check `data/settings.json`: the targets match the contract, every queue is in one of the three team lists, the OLAs are the ones the internal team leads actually agreed, and the period is right.
3. Run `python -m eucreview review data/ --title "EUC service review · October"`.
4. Open `output/report.html`. Read "Raise first" and the scorecard. If a figure surprises you, open `breaches.csv` and look at five tickets before the meeting, not during it.
5. Send the provider `breaches.csv` with the `cause` column empty and ask for it back filled in. The provider's own pack will show a higher compliance; the gap is usually tickets they excluded (pending, "customer caused", duplicates) and that is the first conversation.

## The agenda (`service-review.md`)

1. **Scorecard**: each type × priority against the target. Agree the numbers before discussing causes. Disagreements about exclusions go to a list, not to the meeting.
2. **To raise with the provider**: the findings owned by them, worst first. For each: the cause, the fix, the owner on their side, the date. The report's "Ask" line is the opening question.
3. **What we owe the provider**: OLA misses and old backlog sitting with internal teams. Say it out loud; a provider that is waiting on the network team for 12 tickets will say so anyway.
4. **Contract**: service credits due, volume against the baseline. Credits are claimed or waived in writing; "we'll see next month" is a waiver.
5. **Actions**: `actions.csv` with owner and due date. Last month's actions are reviewed first, not last.

## After

- Keep `output/` for the month (rename the folder) so next month's review can compare.
- Put the agreed exclusions in writing and, if they are permanent, into the measurement rules: `pending_hours`, which statuses stop the clock, which categories are out of scope.
- Three months of the same finding is not a finding, it is the service. Change the target, the staffing or the provider.

## Working with an offshore service desk

- Measure out-of-hours response separately (Coverage): follow-the-sun hand-overs are where P2s wait.
- First-contact resolution tells you whether the desk has the access and the knowledge to fix things, or only to log them.
- Escalation rate and late hand-offs tell you whether the desk is a front door or a filter. Both are fine; agree which one you are paying for.
