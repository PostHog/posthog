
"""
One approach - we build some abstract framework where the only things we really demand of the caller is:
- The actual prompt to research the signal
- source_product and source_identifier

And then have a whole bunch of defaults around how we prompt for assignment, actionability, as well as allowing overriding
of the priority, actionabiltiy etc functions themsselves. Extremely low effort to get started, but still provides the flexibility
to customize the behavior without needing to write a lot of boilerplate. On the other hand, requires us to be quite perscriptive about
exactly how research works
"""
from stripe import Price
from posthog.constants import ACTIONS
from django.utils.timezone import override

class MyResearchAgent(SignalResearchAgent):
    identifier = "my_research_agent"
    source_product = "experiments"
    source_type = "some_type"

    def __init__(self):
        super().__init__()

    # TODO - with this and the below, I don't actually know that this is the right structure - do we /need/ to support multi-step research?
    # We do it for signals, but I think with the "directly write a report" approach, we don't really expect to need it?
    def get_research_step(self, step: int) -> str | None:
        # Always required to tell us how to research the report, supporting multi-step via step index
        if step == 0:
            return "MY INDIVIDUAL STEP PROMPT HERE"
        return None

    def get_final_report_prompt(self) -> str:
        return "MY FINAL REPORT PROMPT HERE"


    @override
    def get_priority_prompt(self) -> str:
        return "This is me, overriding the default prioritisation approach"

    @override
    def get_reviewer_selection_prompt(self) -> str:
        return "This is me, overriding the default reviewer assignment approach, to say something like 'only choose reviewers based on codeowners'"

    @override
    def get_formatting_prompt_chunk(self) -> str:
        return "This is me, overriding the default formatting approach"


    @override
    def get_priority(self) -> Priority:
        # We actually want these reports to always at least be p4
        assigned_priority = super().get_priority()
        if assigned_priority < Priority.P4:
            return Priority.P4
        return assigned_priority

    @override
    def get_actionability(self) -> Actionability:
        # We always want these reports to be immediately actionable
        return Actionability.IMMEDIATELY_ACTIONABLE

#Then, the above would be run like (and this would handle starting the research workflow, backoff, retry, etc etc):
signals.run_research(MyResearchAgent(), title="Some Title", report="Some kind of report stuff", team=Team)

"""
Another approach - we provide well typed functional building blocks as actions, and let people build their own custom workflows.
"""

@action
def get_reviewers(session: MultiTurnSession) -> list[User]:
    pass

@action
def get_priority(session: MultiTurnSession) -> Priority:
    pass

@action
def get_actionability(session: MultiTurnSession) -> Actionability:
    pass

# And finally, the function that puts it all together and actually puts the report in the inbox. This
# is how we ensure callers actually provide everything we need to do auto-starting etc
def emit_report(priority: Priority, actionability: Actionability, ):
    pass

"""
I think this approach has some major downsides, the biggest of which is that it's very hard for us change what we need
to do auto-starting, or to include things in the report, and we expect to need to do this (we've already had discussions about
how we want to add some notion how how likely we are to be able to one-shot something vs. how important the change is, e.g priority
vs. feasibility, and how we might want to incorporate that into auto-starting)

The class driven approach above makes it easy to add new steps, or remove steps, or whatever we want to do, without needing to
change everyones code, at the cost of being a bit more perscriptive about exactly how research works, with no real support for more
complex intermediate objects or steps (e.g. if someone wanted to interact with the django ORM in response to something the agent
returned, the sketch about doesn't support that, although it potentially could...)
"""
