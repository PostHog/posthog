## S: 11 findings after dedup, real 4 (36%), not real 7, real clusters [23, 25, 61, 73], new real 0

- REAL S2 sev=must_fix cluster=61 Migration introduces a conflicting 0019 leaf
- REAL S7 sev=consider cluster=25 A ReviewHog callback failure can prevent the independent Sta
- REAL S9 sev=consider cluster=23 Unmatched bot PRs can trigger an unindexed TaskRun branch sc
- REAL S10 sev=consider cluster=73 Branch fallback can authorize a different PR
- not S1 cluster=3 Security-sensitive flag accepts arbitrary truthy values
- not S3 cluster=4 Self-driving reviews can still include bot familiarity signa
- not S4 cluster=2 Initial inbox path can mark an unrelated PR as self-driving
- not S5 cluster=39 Team scoping is applied only after a cross-tenant TaskRun qu
- not S6 cluster=57 Only one assignee's opt-in is considered
- not S8 cluster=42 Head-keyed deduplication does not serialize concurrent task
- not S11 cluster=31 Queued initial reviews ignore later opt-out

## W: 13 findings after dedup, real 4 (31%), not real 9, real clusters [1, 2, 39, 61], new real 0

- REAL W4 sev=must_fix cluster=61 Migration creates a conflicting leaf in the review_hog graph
- REAL W6 sev=must_fix cluster=2 Initial inbox review does not verify the PR belongs to the t
- REAL W11 sev=should_fix cluster=1 Inbox implementation runs are rejected before either review
- REAL W8 sev=consider cluster=39 Team scoping is applied after an unscoped, nondeterministic
- not W1 cluster=54 Fire-and-forget facade performs a synchronous, failure-propa
- not W2 cluster=4 Self-driving reviews still perform expensive author-familiar
- not W3 cluster=58 Transient broker failures permanently drop the initial Stamp
- not W5 cluster=3 Fail closed when parsing the privileged review flag
- not W7 cluster=57 Stamphog opt-in checks only one assignee instead of any assi
- not W9 cluster=4 Self-driving reviews still include bot-author familiarity si
- not W10 cluster=15 Replica lag can permanently suppress inbox re-reviews
- not W12 cluster=31 Queued initial reviews ignore toggle changes before executio
- not W13 cluster=74 Self-driving prompt still includes human-author ownership si

## KB: 10 findings after dedup, real 4 (40%), not real 6, real clusters [1, 2, 35, 57], new real 0

- REAL KB6 sev=must_fix cluster=2 Revalidate inbox provenance before granting the review carve
- REAL KB7 sev=should_fix cluster=1 The receiver skips real self-driving implementation tasks
- REAL KB8 sev=should_fix cluster=57 The toggle check ignores other assigned reviewers
- REAL KB2 sev=consider cluster=35 Trusted prompt can report the wrong draft state
- not KB1 cluster=39 Post-query team filtering can hide the correct task run
- not KB3 cluster=58 Broker failures permanently lose the initial review
- not KB4 cluster=58 Exhausted retries can leave a review run queued forever
- not KB5 cluster=2 Documented linkage check does not exist on the initial revie
- not KB9 cluster=9 Repeated saves cause a GitHub request before deduplication
- not KB10 cluster=31 The queued review ignores a later opt-out

## KC: 7 findings after dedup, real 3 (43%), not real 4, real clusters [2, 35, 57], new real 0

- REAL KC6 sev=must_fix cluster=2 The initial review task trusts stale and unverified provenan
- REAL KC7 sev=should_fix cluster=57 Stamphog ignores enabled settings from secondary reviewers
- REAL KC5 sev=consider cluster=35 Do not claim that every self-driving PR is a draft
- not KC1 cluster=3 Validate the gate flag as a JSON boolean
- not KC2 cluster=39 Post-filtering an unscoped task-run lookup can hide the corr
- not KC3 cluster=58 A broker failure permanently drops the initial review
- not KC4 cluster=58 Broker failure can permanently lose the initial review

## LA: 23 findings after dedup, real 12 (52%), not real 11, real clusters [1, 2, 6, 8, 23, 29, 35, 57, 75], new real ['LA8', 'LA15']

- REAL LA11 sev=must_fix cluster=2 Verify trusted PR provenance before enabling approval bypass
- REAL LA13 sev=must_fix cluster=2 Validate the PR before granting self-driving privileges
- REAL LA14 sev=must_fix cluster=75 Verify the PostHog Code bot identity
- REAL LA15 sev=must_fix cluster=None Do not use mutable task attribution as authorization
- REAL LA19 sev=must_fix cluster=6 The carve-out is not bound to the expected PR shape
- REAL LA4 sev=should_fix cluster=29 Dependency outages can leave stale approvals active
- REAL LA17 sev=should_fix cluster=57 Stamphog ignores opt-ins from secondary assigned reviewers
- REAL LA18 sev=should_fix cluster=1 The lookup rejects production self-driving tasks
- REAL LA3 sev=consider cluster=35 The trusted prompt always claims the PR is a draft
- REAL LA7 sev=consider cluster=8 Expose Stamphog repository coverage in the switch
- REAL LA8 sev=consider cluster=None Do not order different heads by equal timestamps
- REAL LA21 sev=consider cluster=23 Branch fallback can scan the task-run table
- not LA1 cluster=58 A broker failure permanently loses the initial review
- not LA2 cluster=13 The PR URL parser accepts non-GitHub hosts
- not LA5 cluster=58 Broker failures permanently lose initial review requests
- not LA6 cluster=58 Worker loss or short outages can strand initial reviews
- not LA9 cluster=4 Self-driving mode does not suppress author familiarity
- not LA10 cluster=2 Initial inbox path does not verify the claimed provenance
- not LA12 cluster=None Revoke approval authority when the reviewer loses project ac
- not LA16 cluster=39 Apply the team scope before selecting a run
- not LA20 cluster=31 Queued reviews do not recheck the opt-in
- not LA22 cluster=76 Pin approval gate reads to the writer
- not LA23 cluster=None Preserve the source environment during re-review lookup

## MA: 19 findings after dedup, real 12 (63%), not real 7, real clusters [1, 2, 21, 29, 35, 57], new real ['MA9']

- REAL MA6 sev=must_fix cluster=2 Caller-writable PR URLs can activate the trusted carve-out
- REAL MA7 sev=must_fix cluster=2 Untrusted TaskRun output can authorize an unrelated PR
- REAL MA8 sev=must_fix cluster=2 Initial review trusts a caller-controlled PR URL
- REAL MA9 sev=must_fix cluster=None Caller-writable task fields cannot prove PR provenance
- REAL MA10 sev=must_fix cluster=2 Authenticate self-driving provenance before bypassing approv
- REAL MA1 sev=should_fix cluster=29 Carve-out failures bypass approval retraction
- REAL MA5 sev=should_fix cluster=57 One opted-out reviewer blocks other opted-in reviewers
- REAL MA11 sev=should_fix cluster=57 The Stamphog gate ignores opted-in secondary reviewers
- REAL MA13 sev=should_fix cluster=29 Resolver failures can leave stale approvals active
- REAL MA16 sev=should_fix cluster=1 Production self-driving tasks never reach the new dispatch
- REAL MA19 sev=should_fix cluster=21 Failed and canceled task runs remain eligible for re-review
- REAL MA3 sev=consider cluster=35 The trusted prompt always states that the PR is a draft
- not MA2 cluster=None Child environment access reaches parent Stamphog settings
- not MA4 cluster=58 Broker failures can lose the initial review
- not MA12 cluster=39 Team filters run after candidate selection
- not MA14 cluster=58 Broker failures permanently lose initial reviews
- not MA15 cluster=58 Temporal outages can strand queued runs
- not MA17 cluster=None Parent team IDs block child-environment re-reviews
- not MA18 cluster=31 The queued task does not recheck the reviewer toggle

## LB: 22 findings after dedup, real 11 (50%), not real 11, real clusters [2, 21, 35, 57], new real ['LB2', 'LB17', 'LB20', 'LB21', 'LB22']

- REAL LB8 sev=must_fix cluster=2 Caller-writable PR URL can bypass Stamphog approval gates
- REAL LB10 sev=must_fix cluster=2 Do not trust an unbound context flag to bypass approval gate
- REAL LB12 sev=must_fix cluster=2 Self-driving provenance is granted before the PR is verified
- REAL LB11 sev=should_fix cluster=57 Stamphog ignores opted-in secondary reviewers
- REAL LB13 sev=should_fix cluster=21 Canceled implementation runs still qualify for the carve-out
- REAL LB17 sev=should_fix cluster=None Record hosted WAIT outcomes for self-driving reviews
- REAL LB22 sev=should_fix cluster=None Hosted bot predicate omits posthog-bot
- REAL LB2 sev=consider cluster=None An older completed run can hide the latest failed re-review
- REAL LB3 sev=consider cluster=35 Trusted prompt always claims the PR is a draft
- REAL LB20 sev=consider cluster=None The opt-out path leaves the old review workflow active
- REAL LB21 sev=consider cluster=None The opt-out dismissal misses GitHub-only approvals
- not LB1 cluster=None Self-driving attribution excludes failed reviews
- not LB4 cluster=7 The fail-soft check can delay requests and flood error logs
- not LB5 cluster=58 Worker loss can permanently drop the initial review
- not LB6 cluster=58 Broker failures lose the review request
- not LB7 cluster=None Child access can enable a parent project's approval toggle
- not LB9 cluster=13 The PR URL parser accepts embedded GitHub URLs
- not LB14 cluster=None Report-linked discussion tasks are classified as implementat
- not LB15 cluster=58 A broker failure permanently drops the initial review
- not LB16 cluster=39 Eligibility filters run after selecting one task run
- not LB18 cluster=None Child-environment PRs never receive Stamphog re-reviews
- not LB19 cluster=None Former project members can remain approval reviewers

## MB: 20 findings after dedup, real 13 (65%), not real 7, real clusters [2, 35, 41, 57, 70], new real ['MB5', 'MB12', 'MB13', 'MB17']

- REAL MB8 sev=must_fix cluster=2 Bind the gate bypass to verified PR provenance
- REAL MB14 sev=must_fix cluster=2 Receiver path does not prove that the task created the PR
- REAL MB15 sev=must_fix cluster=2 Do not trust caller-writable TaskRun output as approval prov
- REAL MB16 sev=must_fix cluster=2 Initial inbox reviews trust a caller-controlled PR URL
- REAL MB17 sev=must_fix cluster=None The re-review gate treats writable task fields as proof
- REAL MB6 sev=should_fix cluster=41 Failed reviews can restart without a limit
- REAL MB7 sev=should_fix cluster=70 Add the bot exception to the system prompt
- REAL MB11 sev=should_fix cluster=57 Check every assigned reviewer's opt-in
- REAL MB19 sev=should_fix cluster=57 The Stamphog toggle ignores opted-in secondary reviewers
- REAL MB2 sev=consider cluster=35 Trusted prompt claims ready PRs are drafts
- REAL MB5 sev=consider cluster=None Head-only dedupe accepts a changed base diff
- REAL MB12 sev=consider cluster=None Opt-out dismissal misses approvals that exist only on GitHub
- REAL MB13 sev=consider cluster=None Equal GitHub timestamps can supersede the current run
- not MB1 cluster=31 Recheck the toggle when the queued task runs
- not MB3 cluster=58 A broker outage permanently drops the initial review
- not MB4 cluster=42 Concurrent output saves can start duplicate reviews
- not MB9 cluster=58 Initial review dispatch is not durable
- not MB10 cluster=58 Worker loss can drop the review task
- not MB18 cluster=39 Team scoping occurs after selecting a cross-tenant run
- not MB20 cluster=None Verify the task is an implementation task

## NA: 22 findings after dedup, real 11 (50%), not real 11, real clusters [1, 2, 6, 25, 35, 57, 75], new real ['NA11', 'NA19']

- REAL NA5 sev=must_fix cluster=75 The carve-out accepts any bot identity
- REAL NA7 sev=must_fix cluster=2 The initial path does not verify that the task produced the
- REAL NA10 sev=must_fix cluster=2 Initial inbox reviews trust a caller-controlled PR URL
- REAL NA11 sev=must_fix cluster=None Webhook linkage trusts a user-writable PR URL
- REAL NA22 sev=must_fix cluster=6 Bind the carve-out to the fetched PR
- REAL NA1 sev=should_fix cluster=57 The toggle ignores opted-in secondary assignees
- REAL NA13 sev=should_fix cluster=57 Stamphog ignores opted-in secondary reviewers
- REAL NA14 sev=should_fix cluster=1 Internal implementation runs never qualify
- REAL NA2 sev=consider cluster=35 Trusted prompt reports a ready PR as draft
- REAL NA19 sev=consider cluster=None Resolve equal GitHub timestamps before superseding
- REAL NA20 sev=consider cluster=25 ReviewHog startup runs before the Stamphog-first dispatch
- not NA3 cluster=7 A Stamphog outage can delay every settings response
- not NA4 cluster=58 Persist the review handoff before publishing
- not NA6 cluster=58 Use late acknowledgement for the idempotent task
- not NA8 cluster=57 The documented toggle gate conflicts with the feature contra
- not NA9 cluster=31 A queued initial review can run after opt-out
- not NA12 cluster=3 Truthy JSON can enable the approval carve-out
- not NA15 cluster=None The queue callback imports the full Stamphog worker stack
- not NA16 cluster=58 A broker failure permanently drops the initial review
- not NA17 cluster=9 Repeated output saves create duplicate GitHub fetches
- not NA18 cluster=39 Apply TaskRun scope before selecting a row
- not NA21 cluster=31 Re-check the opt-in inside the delayed task

## NB: 22 findings after dedup, real 11 (50%), not real 11, real clusters [2, 21, 23, 29, 35, 50, 57, 75], new real ['NB9', 'NB21']

- REAL NB2 sev=must_fix cluster=75 The webhook carve-out accepts any bot author
- REAL NB8 sev=must_fix cluster=2 Initial inbox reviews trust client-writable provenance
- REAL NB9 sev=must_fix cluster=None Webhook carve-out uses writable output as provenance
- REAL NB10 sev=must_fix cluster=2 Do not authorize the carve-out with an unchecked truthy flag
- REAL NB11 sev=should_fix cluster=57 Stamphog ignores opted-in secondary reviewers
- REAL NB18 sev=should_fix cluster=29 Fail closed when the webhook resolver cannot read settings
- REAL NB20 sev=should_fix cluster=21 Failed and canceled runs still qualify for re-review
- REAL NB3 sev=consider cluster=35 Ready re-reviews get false trusted draft context
- REAL NB14 sev=consider cluster=50 Base-retarget dismissal promises a review after opt-out
- REAL NB17 sev=consider cluster=23 Index the TaskRun branch fallback
- REAL NB21 sev=consider cluster=None Opt-out can leave an untracked approval active
- not NB1 cluster=None Authorize settings against the canonical team
- not NB4 cluster=58 Broker failures permanently drop initial Stamphog reviews
- not NB5 cluster=58 Initial review dispatch has no durable record
- not NB6 cluster=37 The hosted bypass list omits the author-association gate
- not NB7 cluster=None Require a recorded implementation relationship
- not NB12 cluster=39 Post-selection filters can hide the qualifying signal run
- not NB13 cluster=None A disable race can create a review after repository opt-out
- not NB15 cluster=58 Use late acknowledgements for the initial review task
- not NB16 cluster=58 Exhausted retries can strand queued reviews
- not NB19 cluster=None Non-implementation signal tasks receive the carve-out
- not NB22 cluster=31 Delayed initial tasks ignore a later toggle opt-out

## PA: 14 findings after dedup, real 7 (50%), not real 7, real clusters [2, 6, 29, 35, 57, 75], new real 0

- REAL PA1 sev=must_fix cluster=75 Any bot can qualify through the branch fallback
- REAL PA8 sev=must_fix cluster=2 The initial task trusts caller-supplied PR provenance
- REAL PA10 sev=must_fix cluster=6 The carve-out trusts an unvalidated boolean
- REAL PA11 sev=must_fix cluster=2 Inbox provenance is granted without verifying the pull reque
- REAL PA6 sev=should_fix cluster=29 A resolver failure can leave a stale approval active
- REAL PA12 sev=should_fix cluster=57 The Stamphog gate ignores later opted-in assignees
- REAL PA2 sev=consider cluster=35 The trusted prompt reports ready pull requests as drafts
- not PA3 cluster=51 Fail-soft database check can flood error logs
- not PA4 cluster=58 The initial review handoff can be lost when the broker is un
- not PA5 cluster=58 A worker crash can discard the initial review task
- not PA7 cluster=57 The toggle gate does not match the promised assignee behavio
- not PA9 cluster=31 The worker does not recheck the review opt-in
- not PA13 cluster=39 Post-filtering an unscoped run can hide a valid match
- not PA14 cluster=58 Initial Stamphog dispatch can be lost permanently

## PB: 15 findings after dedup, real 7 (47%), not real 8, real clusters [2, 35, 57], new real ['PB5']

- REAL PB6 sev=must_fix cluster=2 The documented positive-linkage invariant is not enforced
- REAL PB7 sev=must_fix cluster=2 Validate PR provenance before granting the inbox review carv
- REAL PB8 sev=must_fix cluster=2 Untrusted task output enables the privileged review path
- REAL PB9 sev=must_fix cluster=2 The carve-out trusts an unverified context value
- REAL PB10 sev=should_fix cluster=57 The Stamphog gate ignores opted-in secondary reviewers
- REAL PB2 sev=consider cluster=35 The trusted prompt can report the wrong draft state
- REAL PB5 sev=consider cluster=None Opt-out path can leave a late approval active
- not PB1 cluster=13 PR URL parser accepts non-GitHub and ambiguous URLs
- not PB3 cluster=58 Broker failures permanently lose the initial review
- not PB4 cluster=58 Exhausted workflow-start retries leave runs queued forever
- not PB11 cluster=39 Run eligibility is checked after selecting one candidate
- not PB12 cluster=15 The side-effect gate can read a stale TaskRun
- not PB13 cluster=58 Broker failures permanently drop the initial review
- not PB14 cluster=16 Deferred import can escape the save path
- not PB15 cluster=31 A queued review ignores a later opt-out
