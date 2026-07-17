from rest_framework import serializers


class WoWChangeSerializer(serializers.Serializer):
    percent = serializers.IntegerField(help_text="Absolute percentage change, rounded to nearest integer.")
    direction = serializers.ChoiceField(
        choices=["Up", "Down"], help_text="Direction of the change relative to the prior period."
    )
    color = serializers.CharField(help_text="Hex color indicating whether the change is a positive or negative signal.")
    text = serializers.CharField(help_text="Short label, e.g. 'Up 12%'.")
    long_text = serializers.CharField(help_text="Verbose label, e.g. 'Up 12% from prior period'.")


class NumericMetricSerializer(serializers.Serializer):
    current = serializers.FloatField(help_text="Value for the most recent period.")
    previous = serializers.FloatField(allow_null=True, help_text="Value for the prior period, if available.")
    change = WoWChangeSerializer(allow_null=True, help_text="Period-over-period change, null when not meaningful.")


class DurationMetricSerializer(serializers.Serializer):
    current = serializers.CharField(help_text="Human-readable duration, e.g. '2m 34s'.")
    previous = serializers.CharField(allow_null=True, help_text="Prior-period duration, e.g. '2m 10s'.")
    change = WoWChangeSerializer(allow_null=True, help_text="Period-over-period change, null when not meaningful.")


class TopPageSerializer(serializers.Serializer):
    host = serializers.CharField(allow_blank=True, help_text="Host for the page, if recorded.")
    path = serializers.CharField(allow_blank=True, help_text="URL path.")
    visitors = serializers.IntegerField(help_text="Unique visitors in the period.")
    change = WoWChangeSerializer(
        allow_null=True, help_text="Period-over-period change in visitors, null when not meaningful."
    )


class TopSourceSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Initial referring domain.")
    visitors = serializers.IntegerField(help_text="Unique visitors from this source.")
    change = WoWChangeSerializer(
        allow_null=True, help_text="Period-over-period change in visitors, null when not meaningful."
    )


class GoalSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Goal name (action name).")
    conversions = serializers.IntegerField(help_text="Total conversions in the period.")
    change = WoWChangeSerializer(
        allow_null=True, help_text="Period-over-period change in conversions, null when not meaningful."
    )


class WeeklyDigestResponseSerializer(serializers.Serializer):
    visitors = NumericMetricSerializer(help_text="Unique visitors.")
    pageviews = NumericMetricSerializer(help_text="Total pageviews.")
    sessions = NumericMetricSerializer(help_text="Total sessions.")
    bounce_rate = NumericMetricSerializer(help_text="Bounce rate (0–100).")
    avg_session_duration = DurationMetricSerializer(help_text="Average session duration.")
    top_pages = TopPageSerializer(many=True, help_text="Top 5 pages by unique visitors.")
    top_sources = TopSourceSerializer(many=True, help_text="Top 5 traffic sources by unique visitors.")
    goals = GoalSerializer(many=True, help_text="Goal conversions.")
    dashboard_url = serializers.URLField(help_text="Link to the Web analytics dashboard for this project.")


class RecapPersonaSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text=(
            "Stable persona identifier. One of: just_getting_started, conversion_machine, traffic_magnet, "
            "crowd_favorite, search_hog, word_of_mouth, loyal_following, rising_star, steady_hog."
        )
    )
    name = serializers.CharField(help_text="Display name for the persona, e.g. 'Traffic Magnet'.")
    emoji = serializers.CharField(help_text="Emoji representing the persona.")
    blurb = serializers.CharField(help_text="One-line explanation of why this persona was assigned this week.")
    color = serializers.CharField(help_text="Hex accent color for rendering the persona card.")


class RecapHighlightSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable highlight identifier, e.g. 'milestone', 'rising_page', 'top_source'.")
    emoji = serializers.CharField(help_text="Emoji for the highlight.")
    title = serializers.CharField(help_text="Short headline for the highlight, e.g. 'Rising star page'.")
    value = serializers.CharField(help_text="The standout value, e.g. a page path or visitor count.")
    detail = serializers.CharField(allow_blank=True, help_text="Supporting sentence for the highlight.")


class WebAnalyticsRecapResponseSerializer(WeeklyDigestResponseSerializer):
    persona = RecapPersonaSerializer(help_text="The single weekly persona assigned from this week's data.")
    highlights = RecapHighlightSerializer(
        many=True, help_text="Up to three screenshot-worthy superlatives for the week."
    )
    period_label = serializers.CharField(help_text="Human-readable period label, e.g. 'Last 7 days'.")
    period_start = serializers.DateField(help_text="First date included in the recap period, in the project timezone.")
    period_end = serializers.DateField(help_text="Final date included in the recap period, in the project timezone.")
    project_name = serializers.CharField(help_text="Name of the project this recap is for.")
    recap_url = serializers.URLField(help_text="Canonical link to this project's weekly recap.")
