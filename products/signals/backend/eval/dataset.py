from dataclasses import dataclass, field


@dataclass
class SeedSignal:
    content: str
    weight: float = 0.5


@dataclass
class SeedReport:
    key: str
    title: str
    summary: str
    signals: list[SeedSignal] = field(default_factory=list)


@dataclass
class EvalSignalCase:
    description: str
    expected_report_key: str | None
    source_product: str = "session-summaries"
    source_type: str = "pattern"


SEED_REPORTS: list[SeedReport] = [
    SeedReport(
        key="checkout_payment_errors",
        title="Checkout payment failures",
        summary="Users are encountering payment errors during checkout, leading to abandoned carts.",
        signals=[
            SeedSignal(
                content="User encountered a 'payment failed' error on the checkout page after entering their credit card details.",
            ),
            SeedSignal(
                content="User tried to complete a purchase but received a server error (500) on the payment form.",
            ),
            SeedSignal(
                content="User clicked 'Pay Now' and saw a spinning loader for 30 seconds before getting a payment declined message.",
            ),
            SeedSignal(
                content="User's checkout session crashed with an error after submitting payment information.",
            ),
        ],
    ),
    SeedReport(
        key="onboarding_confusion",
        title="Onboarding wizard confusion",
        summary="New users are struggling with the onboarding flow, scrolling and revisiting steps without making progress.",
        signals=[
            SeedSignal(
                content="New user spent 45 seconds on the onboarding wizard, scrolling up and down without clicking any action buttons.",
            ),
            SeedSignal(
                content="User navigated between onboarding steps repeatedly, going back and forth without completing any step.",
            ),
            SeedSignal(
                content="User appeared confused during initial setup, hovering over tooltips multiple times and reopening help panels.",
            ),
        ],
    ),
    SeedReport(
        key="search_performance",
        title="Search response time issues",
        summary="Search functionality is extremely slow, taking 8-15 seconds to return results.",
        signals=[
            SeedSignal(
                content="Search results took over 8 seconds to load, and the user clicked the search button multiple times in frustration.",
            ),
            SeedSignal(
                content="User experienced very slow search response time, waiting approximately 12 seconds before any results appeared.",
            ),
            SeedSignal(
                content="The search functionality was unresponsive for about 10 seconds after the user typed a query, then all results loaded at once.",
            ),
            SeedSignal(
                content="User typed a search query and waited while a loading spinner displayed for 15 seconds before results showed.",
            ),
        ],
    ),
    SeedReport(
        key="dashboard_widget_loading",
        title="Dashboard widgets slow to load",
        summary="Dashboard insight widgets are taking 15-20+ seconds to render, causing users to leave or refresh repeatedly.",
        signals=[
            SeedSignal(
                content="Dashboard took 15+ seconds to fully render all widgets, and the user navigated away before it finished loading.",
            ),
            SeedSignal(
                content="Multiple insight widgets on the main dashboard showed loading spinners for over 20 seconds.",
            ),
            SeedSignal(
                content="User refreshed the dashboard page three times because widgets were stuck in a loading state.",
            ),
        ],
    ),
    SeedReport(
        key="csv_export_failures",
        title="CSV export timeouts",
        summary="Data exports to CSV are failing with timeout errors or producing empty files.",
        signals=[
            SeedSignal(
                content="User's CSV data export failed with a timeout error after waiting approximately 2 minutes.",
            ),
            SeedSignal(
                content="Export to CSV produced an empty file despite the user having data in the selected date range.",
            ),
            SeedSignal(
                content="User attempted to export insights data but received a 'request timed out' error after 90 seconds.",
            ),
        ],
    ),
    SeedReport(
        key="mobile_layout_issues",
        title="Mobile layout overlap problems",
        summary="On mobile devices, UI elements overlap each other, making buttons and controls inaccessible.",
        signals=[
            SeedSignal(
                content="On mobile devices, the sidebar navigation overlapped the main content area, making buttons untappable.",
            ),
            SeedSignal(
                content="Mobile user could not interact with the filter dropdown because it rendered behind the page header.",
            ),
            SeedSignal(
                content="The action toolbar on mobile was cut off at the bottom of the screen, hiding the Save and Cancel buttons.",
            ),
            SeedSignal(
                content="Responsive layout broke on small screens, causing horizontal scroll and misaligned form elements.",
            ),
        ],
    ),
    SeedReport(
        key="signup_verification_dropoff",
        title="Signup drop-off at email verification",
        summary="Users complete the signup form but abandon the flow at the email verification step.",
        signals=[
            SeedSignal(
                content="User filled out the entire signup form but abandoned the flow at the email verification step.",
            ),
            SeedSignal(
                content="Multiple users dropped off during registration right after being asked to verify their email address.",
            ),
            SeedSignal(
                content="User completed all signup fields but left the page when prompted to check their inbox for a verification link.",
            ),
        ],
    ),
    SeedReport(
        key="replay_playback_issues",
        title="Session replay playback failures",
        summary="Session replay videos freeze, show black screens, or fail to seek properly during playback.",
        signals=[
            SeedSignal(
                content="Session replay video froze at the 2-minute mark and would not resume playback.",
            ),
            SeedSignal(
                content="Recording playback showed a black screen after the first 30 seconds, with the timeline still advancing.",
            ),
            SeedSignal(
                content="User tried to seek forward in a session replay but the player jumped back to the beginning each time.",
            ),
        ],
    ),
]


EVAL_CASES: list[EvalSignalCase] = [
    # Straightforward matches
    EvalSignalCase(
        description="User got a payment processing error when clicking 'Complete order' at checkout.",
        expected_report_key="checkout_payment_errors",
    ),
    EvalSignalCase(
        description="First-time user seemed lost during the product setup wizard, revisiting the same instructions repeatedly.",
        expected_report_key="onboarding_confusion",
    ),
    EvalSignalCase(
        description="Search was loading extremely slowly, about 10 seconds before any results appeared on screen.",
        expected_report_key="search_performance",
    ),
    EvalSignalCase(
        description="The insights dashboard widgets were stuck showing loading spinners for over 20 seconds.",
        expected_report_key="dashboard_widget_loading",
    ),
    EvalSignalCase(
        description="Data export to CSV timed out and the download produced no file.",
        expected_report_key="csv_export_failures",
    ),
    EvalSignalCase(
        description="Mobile users cannot tap the 'Save' button because the navigation drawer covers the bottom of the screen.",
        expected_report_key="mobile_layout_issues",
    ),
    EvalSignalCase(
        description="User abandoned the registration flow right after being asked to verify their email.",
        expected_report_key="signup_verification_dropoff",
    ),
    EvalSignalCase(
        description="Session recording playback stuttered and then completely stopped mid-session.",
        expected_report_key="replay_playback_issues",
    ),
    # Harder matches: different phrasing, adjacent context
    EvalSignalCase(
        description="User received a declined payment error after submitting their card on the billing page.",
        expected_report_key="checkout_payment_errors",
    ),
    EvalSignalCase(
        description="User waited over 12 seconds for the search autocomplete suggestions to populate.",
        expected_report_key="search_performance",
    ),
    EvalSignalCase(
        description="On a tablet, the settings panel overlapped with the main content, making checkboxes inaccessible.",
        expected_report_key="mobile_layout_issues",
    ),
    # Signals that should NOT match any existing report
    EvalSignalCase(
        description="User toggled dark mode on and off 5 times in quick succession.",
        expected_report_key=None,
    ),
    EvalSignalCase(
        description="User opened the API documentation page and copied multiple code snippets over a 3-minute period.",
        expected_report_key=None,
    ),
]
