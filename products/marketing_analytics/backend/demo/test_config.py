from posthog.test.base import BaseTest

from products.marketing_analytics.backend.demo.config import build_conversion_goals

SUM_MATHS = {"sum"}


class TestDemoConversionGoals(BaseTest):
    def test_every_revenue_goal_actually_sums_an_amount(self):
        # `counts_as_revenue` without sum math feeds ROAS a conversion count, and the
        # write path rejects it — demo config must not seed a state the API refuses.
        for goal in build_conversion_goals(self.team):
            if goal.get("counts_as_revenue"):
                assert goal.get("math") in SUM_MATHS, goal["conversion_goal_id"]
                assert goal.get("math_property"), goal["conversion_goal_id"]

    def test_a_revenue_shaped_goal_is_left_unflagged(self):
        unflagged = [
            g
            for g in build_conversion_goals(self.team)
            if g.get("math") in SUM_MATHS
            and g.get("math_property")
            and not g.get("counts_as_revenue")
            and not g.get("counts_as_customer")
        ]
        assert unflagged, "nothing drives mark_goal_as_revenue / mark_goal_as_customer"

    def test_both_flags_are_represented(self):
        goals = build_conversion_goals(self.team)
        assert any(g.get("counts_as_revenue") for g in goals)
        assert any(g.get("counts_as_customer") for g in goals)
