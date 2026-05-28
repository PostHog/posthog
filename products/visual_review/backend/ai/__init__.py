"""Agent reviewers for visual_review.

Stand-alone services that look at a completed run and produce a verdict
(approve / reject / defer) per snapshot, plus a rollup for the run. No
side effects beyond writing the verdict into ``RunSnapshot.metadata`` /
``Run.metadata``.
"""
