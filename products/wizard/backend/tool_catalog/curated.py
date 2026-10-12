"""Tools curated by hand: their detection signals and the PostHog products they compete with.

Every warehouse source type without an entry here still gets a derived entry, see `derived.py`.
After editing, run `hogli build:projections` and commit the regenerated
`products/wizard/tool-catalog.generated.json`. The wizard syncs its registry from that file.
"""

from collections.abc import Mapping
from typing import TypedDict, Unpack, cast

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType as Source
from products.wizard.backend.tool_catalog.types import Ecosystem, Tool, ToolOrigin, ToolSignals, WizardSetupMode

IN_CLI = WizardSetupMode.IN_CLI
DEEP_LINK = WizardSetupMode.DEEP_LINK


class _Details(TypedDict, total=False):
    npm: tuple[str, ...]
    pypi: tuple[str, ...]
    rubygems: tuple[str, ...]
    composer: tuple[str, ...]
    hex: tuple[str, ...]
    go: tuple[str, ...]
    cargo: tuple[str, ...]
    maven: tuple[str, ...]
    swiftpm: tuple[str, ...]
    cocoapods: tuple[str, ...]
    pub: tuple[str, ...]
    env: tuple[str, ...]
    script_hosts: tuple[str, ...]
    competes_with: tuple[ProductKey, ...]
    superseded_by: tuple[str, ...]


def _tool(
    kind: str,
    label: str,
    *,
    warehouse_source_type: Source | None,
    setup_mode: WizardSetupMode | None,
    llm: bool,
    details: _Details,
) -> Tool:
    # The package keyword names match the Ecosystem values, so a lookup by value finds them.
    by_name = cast(Mapping[str, tuple[str, ...]], details)
    packages = {ecosystem: by_name[ecosystem.value] for ecosystem in Ecosystem if by_name.get(ecosystem.value)}
    return Tool(
        kind=kind,
        label=label,
        origin=ToolOrigin.CURATED,
        signals=ToolSignals(
            packages=packages,
            env_key_patterns=details.get("env", ()),
            script_hosts=details.get("script_hosts", ()),
        ),
        warehouse_source_type=warehouse_source_type,
        wizard_setup_mode=setup_mode,
        competes_with=details.get("competes_with", ()),
        llm=llm,
        superseded_by=details.get("superseded_by", ()),
    )


def _source(source_type: Source, label: str, setup_mode: WizardSetupMode, **details: Unpack[_Details]) -> Tool:
    return _tool(
        source_type.value, label, warehouse_source_type=source_type, setup_mode=setup_mode, llm=False, details=details
    )


def _llm_source(source_type: Source, label: str, setup_mode: WizardSetupMode, **details: Unpack[_Details]) -> Tool:
    return _tool(
        source_type.value, label, warehouse_source_type=source_type, setup_mode=setup_mode, llm=True, details=details
    )


def _competitor(kind: str, label: str, **details: Unpack[_Details]) -> Tool:
    """A competitor PostHog has no warehouse source for. The wizard detects and reports it, never offers it."""
    return _tool(kind, label, warehouse_source_type=None, setup_mode=None, llm=False, details=details)


CURATED_TOOLS: tuple[Tool, ...] = (
    # NOTE: DATABASE_URL is ambiguous - MySQL/SQLite projects (Prisma,
    # Rails) use it too. We only read key NAMES, not the scheme, so this
    # is a deliberate precision/recall tradeoff biased toward the most
    # common convention (DATABASE_URL -> Postgres).
    # Neon and Supabase are hosted Postgres, and a project on either still
    # names its connection with the generic signals above. Two sources over
    # one database import the same tables twice.
    _source(
        Source.POSTGRES,
        "PostgreSQL",
        IN_CLI,
        npm=("pg", "postgres", "postgres.js", "knex", "sequelize"),
        pypi=("psycopg", "psycopg2", "psycopg2-binary", "asyncpg"),
        rubygems=("pg",),
        env=("^DATABASE_URL$", "^POSTGRES_", "^PG(HOST|DATABASE|USER|PORT)$"),
        superseded_by=("Neon", "Supabase"),
    ),
    _source(
        Source.MYSQL,
        "MySQL",
        IN_CLI,
        npm=("mysql", "mysql2"),
        pypi=("pymysql", "mysqlclient", "mysql-connector-python"),
        rubygems=("mysql2",),
        env=("^MYSQL_",),
    ),
    # Matches both MONGO_* and MONGODB_* prefixes (e.g. MONGO_HOST,
    # MONGODB_URI) in one pattern.
    _source(
        Source.MONGODB,
        "MongoDB",
        IN_CLI,
        npm=("mongodb", "mongoose"),
        pypi=("pymongo", "motor"),
        rubygems=("mongo", "mongoid"),
        env=("^MONGO(DB)?_",),
    ),
    _source(
        Source.SNOWFLAKE,
        "Snowflake",
        IN_CLI,
        npm=("snowflake-sdk",),
        pypi=("snowflake-connector-python", "snowflake-sqlalchemy"),
        env=("^SNOWFLAKE_",),
    ),
    # BigQuery authenticates with a Google Cloud service-account JSON key
    # file, like Firebase above - the source's only required credential field
    # is a file upload, and the terminal prompt collects single-line text, so
    # there is no in-cli path that can accept it. Deep-link to the app's
    # new-source form instead of dead-ending on an unpasteable credential.
    _source(
        Source.BIGQUERY,
        "BigQuery",
        DEEP_LINK,
        npm=("@google-cloud/bigquery",),
        pypi=("google-cloud-bigquery",),
        env=("^BIGQUERY_",),
    ),
    _source(
        Source.REDSHIFT, "Redshift", IN_CLI, npm=("node-redshift",), pypi=("redshift-connector",), env=("^REDSHIFT_",)
    ),
    _source(Source.MSSQL, "SQL Server", IN_CLI, npm=("mssql", "tedious"), pypi=("pyodbc", "pymssql"), env=("^MSSQL_",)),
    _source(
        Source.SUPABASE, "Supabase", IN_CLI, npm=("@supabase/supabase-js",), pypi=("supabase",), env=("^SUPABASE_",)
    ),
    _source(
        Source.CLICKHOUSE,
        "ClickHouse",
        IN_CLI,
        npm=("@clickhouse/client",),
        pypi=("clickhouse-connect", "clickhouse-driver"),
        env=("^CLICKHOUSE_",),
    ),
    _source(
        Source.CONVEX, "Convex", IN_CLI, npm=("convex",), pypi=("convex",), env=("^CONVEX_", "^NEXT_PUBLIC_CONVEX_URL$")
    ),
    # Firebase authenticates with a service-account JSON key file, not a
    # pasteable string. The terminal credential prompt only collects
    # single-line text, so there is no safe in-cli path: the file upload lives
    # in the app's new-source form. Deep-link there instead of dead-ending on a
    # credential the CLI cannot accept.
    # NOTE: the `firebase` client SDK also covers auth-only projects, which
    # have no Firestore data to import. We accept the false positives - the
    # package is a strong signal for the common case.
    _source(
        Source.FIREBASE,
        "Firebase",
        DEEP_LINK,
        npm=("firebase-admin", "firebase"),
        pypi=("firebase-admin",),
        env=("^FIREBASE_", "^NEXT_PUBLIC_FIREBASE_"),
    ),
    _source(Source.NEON, "Neon", IN_CLI, npm=("@neondatabase/serverless",), env=("^NEON_",)),
    _source(
        Source.PLANETSCALEMYSQL, "PlanetScale MySQL", IN_CLI, npm=("@planetscale/database",), env=("^PLANETSCALE_",)
    ),
    _source(
        Source.DYNAMODB,
        "DynamoDB",
        IN_CLI,
        npm=("@aws-sdk/client-dynamodb", "@aws-sdk/lib-dynamodb"),
        pypi=("pynamodb",),
    ),
    _source(Source.MOTHERDUCK, "MotherDuck", IN_CLI, npm=("@motherduck/wasm-client",), env=("^MOTHERDUCK_",)),
    _source(
        Source.DATABRICKS,
        "Databricks",
        IN_CLI,
        npm=("@databricks/sql",),
        pypi=("databricks-sql-connector", "databricks-sdk"),
        env=("^DATABRICKS_",),
    ),
    _source(Source.SINGLESTORE, "SingleStore", IN_CLI, pypi=("singlestoredb",), env=("^SINGLESTORE_",)),
    _source(
        Source.STRIPE,
        "Stripe",
        IN_CLI,
        npm=("stripe", "@stripe/stripe-js", "@stripe/react-stripe-js"),
        pypi=("stripe",),
        rubygems=("stripe",),
        env=("^STRIPE_(SECRET|API)_KEY$",),
    ),
    _source(
        Source.CLERK,
        "Clerk",
        IN_CLI,
        npm=(
            "@clerk/nextjs",
            "@clerk/clerk-react",
            "@clerk/backend",
            "@clerk/express",
            "@clerk/fastify",
            "@clerk/remix",
        ),
        env=("^CLERK_SECRET_KEY$", "^NEXT_PUBLIC_CLERK_"),
    ),
    _source(Source.RESEND, "Resend", IN_CLI, npm=("resend",), pypi=("resend",), env=("^RESEND_API_KEY$",)),
    _source(
        Source.SHOPIFY,
        "Shopify",
        IN_CLI,
        npm=("@shopify/shopify-api", "shopify-api-node"),
        pypi=("shopifyapi",),
        env=("^SHOPIFY_",),
    ),
    _source(
        Source.KLAVIYO,
        "Klaviyo",
        IN_CLI,
        npm=("klaviyo-api",),
        pypi=("klaviyo-api",),
        env=("^KLAVIYO_",),
        competes_with=(ProductKey.WORKFLOWS,),
    ),
    _source(Source.CHARGEBEE, "Chargebee", IN_CLI, npm=("chargebee",), pypi=("chargebee",), env=("^CHARGEBEE_",)),
    _source(Source.PADDLE, "Paddle", IN_CLI, npm=("@paddle/paddle-node-sdk", "@paddle/paddle-js"), env=("^PADDLE_",)),
    _source(Source.POLAR, "Polar", IN_CLI, npm=("@polar-sh/sdk", "@polar-sh/nextjs"), env=("^POLAR_",)),
    _source(
        Source.MAILCHIMP,
        "Mailchimp",
        IN_CLI,
        npm=("@mailchimp/mailchimp_marketing",),
        pypi=("mailchimp-marketing",),
        env=("^MAILCHIMP_",),
    ),
    _source(
        Source.CUSTOMERIO,
        "Customer.io",
        IN_CLI,
        npm=("customerio-node",),
        pypi=("customerio",),
        env=("^CUSTOMER_?IO_",),
        competes_with=(ProductKey.WORKFLOWS,),
    ),
    _source(
        Source.TYPEFORM,
        "Typeform",
        IN_CLI,
        npm=("@typeform/api-client",),
        env=("^TYPEFORM_",),
        competes_with=(ProductKey.SURVEYS,),
    ),
    _source(
        Source.SENTRY,
        "Sentry",
        IN_CLI,
        npm=("@sentry/node", "@sentry/browser", "@sentry/react", "@sentry/nextjs"),
        pypi=("sentry-sdk",),
        rubygems=("sentry-ruby",),
        competes_with=(ProductKey.ERROR_TRACKING,),
    ),
    _source(
        Source.PLAID,
        "Plaid",
        IN_CLI,
        npm=("plaid",),
        pypi=("plaid-python", "plaid"),
        rubygems=("plaid",),
        env=("^PLAID_",),
    ),
    _source(
        Source.BRAINTREE,
        "Braintree",
        IN_CLI,
        npm=("braintree",),
        pypi=("braintree",),
        rubygems=("braintree",),
        env=("^BRAINTREE_",),
    ),
    _source(
        Source.SQUARE, "Square", IN_CLI, npm=("square",), pypi=("squareup",), rubygems=("square",), env=("^SQUARE_",)
    ),
    _source(
        Source.GOCARDLESS,
        "GoCardless",
        IN_CLI,
        npm=("gocardless-nodejs",),
        pypi=("gocardless-pro",),
        rubygems=("gocardless_pro",),
        env=("^GOCARDLESS_",),
    ),
    _source(
        Source.MOLLIE, "Mollie", IN_CLI, npm=("@mollie/api-client",), pypi=("mollie-api-python",), env=("^MOLLIE_",)
    ),
    # Checkout.com's own convention is the CKO_ prefix.
    _source(
        Source.CHECKOUTCOM,
        "Checkout.com",
        IN_CLI,
        npm=("checkout-sdk-node",),
        pypi=("checkout-sdk",),
        env=("^CKO_", "^CHECKOUT_COM_"),
    ),
    _source(
        Source.RECURLY,
        "Recurly",
        IN_CLI,
        npm=("recurly",),
        pypi=("recurly",),
        rubygems=("recurly",),
        env=("^RECURLY_",),
    ),
    _source(
        Source.REVENUECAT,
        "RevenueCat",
        IN_CLI,
        npm=("@revenuecat/purchases-js", "react-native-purchases", "@revenuecat/purchases-capacitor"),
        env=("^REVENUE_?CAT_",),
    ),
    _source(
        Source.TWILIO, "Twilio", IN_CLI, npm=("twilio",), pypi=("twilio",), rubygems=("twilio-ruby",), env=("^TWILIO_",)
    ),
    _source(
        Source.SENDGRID,
        "SendGrid",
        IN_CLI,
        npm=("@sendgrid/mail", "@sendgrid/client"),
        pypi=("sendgrid",),
        rubygems=("sendgrid-ruby",),
        env=("^SENDGRID_",),
    ),
    _source(
        Source.MAILGUN,
        "Mailgun",
        IN_CLI,
        npm=("mailgun.js", "mailgun-js"),
        pypi=("mailgun",),
        rubygems=("mailgun-ruby",),
        env=("^MAILGUN_",),
    ),
    _source(
        Source.POSTMARK,
        "Postmark",
        IN_CLI,
        npm=("postmark",),
        pypi=("postmarker",),
        rubygems=("postmark",),
        env=("^POSTMARK_",),
    ),
    _source(
        Source.BREVO,
        "Brevo",
        IN_CLI,
        npm=("@getbrevo/brevo", "sib-api-v3-sdk"),
        pypi=("sib-api-v3-sdk",),
        env=("^BREVO_",),
    ),
    _source(
        Source.MAILERLITE,
        "MailerLite",
        IN_CLI,
        npm=("@mailerlite/mailerlite-nodejs",),
        pypi=("mailerlite",),
        env=("^MAILERLITE_",),
    ),
    # Mailjet's documented env convention is MJ_APIKEY_PUBLIC / *_PRIVATE.
    _source(
        Source.MAILJET,
        "Mailjet",
        IN_CLI,
        npm=("node-mailjet",),
        pypi=("mailjet-rest",),
        env=("^MAILJET_", "^MJ_APIKEY_"),
    ),
    _source(
        Source.LAUNCHDARKLY,
        "LaunchDarkly",
        IN_CLI,
        npm=(
            "launchdarkly-node-server-sdk",
            "@launchdarkly/node-server-sdk",
            "launchdarkly-js-client-sdk",
            "launchdarkly-react-client-sdk",
        ),
        pypi=("launchdarkly-server-sdk",),
        rubygems=("launchdarkly-server-sdk",),
        env=("^LAUNCHDARKLY_", "^LD_SDK_KEY$"),
        competes_with=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    ),
    _source(
        Source.OPTIMIZELY,
        "Optimizely",
        IN_CLI,
        npm=("@optimizely/optimizely-sdk",),
        pypi=("optimizely-sdk",),
        env=("^OPTIMIZELY_",),
        competes_with=(ProductKey.EXPERIMENTS,),
    ),
    _source(
        Source.BRAZE,
        "Braze",
        IN_CLI,
        npm=("@braze/web-sdk", "@braze/react-native-sdk"),
        pypi=("braze-client",),
        env=("^BRAZE_",),
        competes_with=(ProductKey.WORKFLOWS,),
    ),
    _source(
        Source.ROLLBAR,
        "Rollbar",
        IN_CLI,
        npm=("rollbar",),
        pypi=("rollbar", "pyrollbar"),
        rubygems=("rollbar",),
        env=("^ROLLBAR_",),
        competes_with=(ProductKey.ERROR_TRACKING,),
    ),
    _source(
        Source.OKTA,
        "Okta",
        IN_CLI,
        npm=("@okta/okta-sdk-nodejs", "@okta/okta-auth-js", "@okta/okta-react"),
        pypi=("okta",),
        env=("^OKTA_",),
    ),
    _source(Source.WORKOS, "WorkOS", IN_CLI, npm=("@workos-inc/node",), pypi=("workos",), env=("^WORKOS_",)),
    _source(Source.NOTION, "Notion", IN_CLI, npm=("@notionhq/client",), pypi=("notion-client",), env=("^NOTION_",)),
    _source(
        Source.FULLSTORY,
        "FullStory",
        IN_CLI,
        npm=("@fullstory/browser", "@fullstory/react-native"),
        env=("^FULLSTORY_",),
        competes_with=(ProductKey.SESSION_REPLAY,),
    ),
    _source(
        Source.AMPLITUDE,
        "Amplitude",
        IN_CLI,
        npm=(
            "@amplitude/analytics-browser",
            "@amplitude/analytics-node",
            "@amplitude/analytics-react-native",
            "amplitude-js",
        ),
        pypi=("amplitude-analytics",),
        env=("^AMPLITUDE_",),
        competes_with=(ProductKey.PRODUCT_ANALYTICS,),
    ),
    _source(
        Source.MIXPANEL,
        "Mixpanel",
        IN_CLI,
        npm=("mixpanel", "mixpanel-browser"),
        pypi=("mixpanel",),
        rubygems=("mixpanel-ruby",),
        env=("^MIXPANEL_",),
        competes_with=(ProductKey.PRODUCT_ANALYTICS,),
    ),
    _source(
        Source.PENDO,
        "Pendo",
        IN_CLI,
        npm=("@pendo/agent",),
        env=("^PENDO_",),
        competes_with=(ProductKey.PRODUCT_ANALYTICS, ProductKey.PRODUCT_TOURS, ProductKey.SURVEYS),
    ),
    _source(
        Source.SALESFORCE, "Salesforce", DEEP_LINK, npm=("jsforce",), pypi=("simple-salesforce",), env=("^SALESFORCE_",)
    ),
    _source(
        Source.HUBSPOT,
        "HubSpot",
        DEEP_LINK,
        npm=("@hubspot/api-client",),
        pypi=("hubspot-api-client",),
        env=("^HUBSPOT_",),
    ),
    _source(
        Source.ZENDESK,
        "Zendesk",
        DEEP_LINK,
        npm=("node-zendesk",),
        pypi=("zenpy",),
        env=("^ZENDESK_",),
        competes_with=(ProductKey.CONVERSATIONS,),
    ),
    _source(
        Source.INTERCOM,
        "Intercom",
        DEEP_LINK,
        npm=("intercom-client", "@intercom/messenger-js-sdk"),
        pypi=("python-intercom",),
        env=("^INTERCOM_",),
        competes_with=(ProductKey.CONVERSATIONS,),
    ),
    _source(Source.LINEAR, "Linear", DEEP_LINK, npm=("@linear/sdk",), env=("^LINEAR_API_KEY$",)),
    # OAuth-only in PostHog (Slack app integration), so deep-link.
    _source(
        Source.SLACK,
        "Slack",
        DEEP_LINK,
        npm=("@slack/web-api", "@slack/bolt"),
        pypi=("slack-sdk", "slack-bolt"),
        env=("^SLACK_(BOT|APP|SIGNING|CLIENT)_",),
    ),
    # 'Github' (not 'GitHub') - matches the ExternalDataSourceType value.
    # Default auth is the GitHub App integration (OAuth), so deep-link.
    _source(
        Source.GITHUB,
        "GitHub",
        DEEP_LINK,
        npm=("@octokit/rest", "@octokit/core", "@octokit/graphql", "octokit"),
        pypi=("pygithub",),
        rubygems=("octokit",),
    ),
    # Additional released source types (see PostHog data-warehouse
    # source catalog). Detected by SDK package or .env key convention.
    # ---- LLM / AI ----
    _llm_source(Source.OPENAI, "OpenAI", IN_CLI, npm=("openai",), pypi=("openai",), env=("^OPENAI_",)),
    _llm_source(
        Source.ANTHROPIC, "Anthropic", IN_CLI, npm=("@anthropic-ai/sdk",), pypi=("anthropic",), env=("^ANTHROPIC_",)
    ),
    _llm_source(Source.COHERE, "Cohere", IN_CLI, npm=("cohere-ai",), pypi=("cohere",), env=("^COHERE_",)),
    _llm_source(
        Source.MISTRALAI, "Mistral AI", IN_CLI, npm=("@mistralai/mistralai",), pypi=("mistralai",), env=("^MISTRAL_",)
    ),
    _llm_source(Source.GROQ, "Groq", IN_CLI, npm=("groq-sdk",), pypi=("groq",), env=("^GROQ_",)),
    _llm_source(
        Source.TOGETHERAI, "Together AI", IN_CLI, npm=("together-ai",), pypi=("together",), env=("^TOGETHER_",)
    ),
    _llm_source(Source.FIREWORKSAI, "Fireworks AI", IN_CLI, pypi=("fireworks-ai",), env=("^FIREWORKS_",)),
    _llm_source(Source.REPLICATE, "Replicate", IN_CLI, npm=("replicate",), pypi=("replicate",), env=("^REPLICATE_",)),
    _llm_source(
        Source.HUGGINGFACE,
        "Hugging Face",
        IN_CLI,
        npm=("@huggingface/inference",),
        pypi=("huggingface-hub",),
        env=("^HUGGINGFACE_", "^HF_TOKEN$"),
    ),
    _llm_source(
        Source.ELEVENLABS,
        "ElevenLabs",
        IN_CLI,
        npm=("@elevenlabs/elevenlabs-js", "elevenlabs"),
        pypi=("elevenlabs",),
        env=("^ELEVENLABS_", "^ELEVEN_LABS_"),
    ),
    _llm_source(
        Source.DEEPGRAM, "Deepgram", IN_CLI, npm=("@deepgram/sdk",), pypi=("deepgram-sdk",), env=("^DEEPGRAM_",)
    ),
    _llm_source(
        Source.ASSEMBLYAI, "AssemblyAI", IN_CLI, npm=("assemblyai",), pypi=("assemblyai",), env=("^ASSEMBLYAI_",)
    ),
    _llm_source(
        Source.LANGFUSE,
        "Langfuse",
        IN_CLI,
        npm=("langfuse",),
        pypi=("langfuse",),
        env=("^LANGFUSE_",),
        competes_with=(ProductKey.LLM_ANALYTICS,),
    ),
    _llm_source(
        Source.LANGSMITH,
        "LangSmith",
        IN_CLI,
        npm=("langsmith",),
        pypi=("langsmith",),
        env=("^LANGSMITH_", "^LANGCHAIN_API_KEY$"),
        competes_with=(ProductKey.LLM_ANALYTICS,),
    ),
    _llm_source(
        Source.FIRECRAWL,
        "Firecrawl",
        IN_CLI,
        npm=("@mendable/firecrawl-js",),
        pypi=("firecrawl-py",),
        env=("^FIRECRAWL_",),
    ),
    _llm_source(Source.MEM0, "Mem0", IN_CLI, npm=("mem0ai",), pypi=("mem0ai",), env=("^MEM0_",)),
    _llm_source(Source.VELLUM, "Vellum", IN_CLI, npm=("vellum-ai",), pypi=("vellum-ai",), env=("^VELLUM_",)),
    _llm_source(
        Source.HELICONE,
        "Helicone",
        IN_CLI,
        npm=("@helicone/helpers",),
        env=("^HELICONE_",),
        competes_with=(ProductKey.LLM_ANALYTICS,),
    ),
    _llm_source(Source.OPENROUTER, "OpenRouter", IN_CLI, npm=("@openrouter/ai-sdk-provider",), env=("^OPENROUTER_",)),
    _llm_source(
        Source.BROWSERBASE,
        "Browserbase",
        IN_CLI,
        npm=("@browserbasehq/sdk", "@browserbasehq/stagehand"),
        pypi=("browserbase",),
        env=("^BROWSERBASE_",),
    ),
    _llm_source(
        Source.E2B,
        "E2B",
        IN_CLI,
        npm=("e2b", "@e2b/code-interpreter"),
        pypi=("e2b", "e2b-code-interpreter"),
        env=("^E2B_",),
    ),
    _llm_source(Source.WEIGHTSANDBIASES, "Weights & Biases", IN_CLI, pypi=("wandb",), env=("^WANDB_",)),
    _llm_source(
        Source.LLAMACLOUD,
        "LlamaCloud",
        IN_CLI,
        npm=("llama-cloud-services",),
        pypi=("llama-cloud-services",),
        env=("^LLAMA_CLOUD_",),
    ),
    _llm_source(Source.ZEP, "Zep", IN_CLI, npm=("@getzep/zep-cloud",), pypi=("zep-cloud",), env=("^ZEP_API_KEY$",)),
    # ---- Payments / billing ----
    _source(Source.PAYSTACK, "Paystack", IN_CLI, pypi=("paystackapi",), env=("^PAYSTACK_",)),
    _source(Source.ORB, "Orb", IN_CLI, npm=("orb-billing",), pypi=("orb-billing",), env=("^ORB_",)),
    _source(
        Source.LAGO, "Lago", IN_CLI, npm=("lago-javascript-client",), pypi=("lago-python-client",), env=("^LAGO_",)
    ),
    _source(Source.ZUORA, "Zuora", IN_CLI, env=("^ZUORA_",)),
    _source(Source.STIGG, "Stigg", IN_CLI, npm=("@stigg/node-server-sdk",), env=("^STIGG_",)),
    _source(Source.RAMP, "Ramp", IN_CLI, env=("^RAMP_",)),
    _source(Source.BREX, "Brex", IN_CLI, env=("^BREX_",)),
    _source(Source.TREMENDOUS, "Tremendous", IN_CLI, env=("^TREMENDOUS_",)),
    _source(Source.MAXIO, "Maxio", IN_CLI, env=("^MAXIO_",)),
    _source(Source.CHARGIFY, "Chargify", IN_CLI, env=("^CHARGIFY_",)),
    _source(Source.INVOICED, "Invoiced", IN_CLI, npm=("invoiced",), pypi=("invoiced",), env=("^INVOICED_",)),
    _source(
        Source.LEMONSQUEEZY,
        "Lemon Squeezy",
        IN_CLI,
        npm=("@lemonsqueezy/lemonsqueezy.js",),
        env=("^LEMONSQUEEZY_", "^LEMON_SQUEEZY_"),
    ),
    _source(
        Source.RAZORPAY,
        "Razorpay",
        IN_CLI,
        npm=("razorpay",),
        pypi=("razorpay",),
        rubygems=("razorpay",),
        env=("^RAZORPAY_",),
    ),
    _source(Source.ADYEN, "Adyen", IN_CLI, npm=("@adyen/api-library",), pypi=("adyen",), env=("^ADYEN_",)),
    _source(
        Source.CHARTMOGUL, "ChartMogul", IN_CLI, npm=("chartmogul-node",), pypi=("chartmogul",), env=("^CHARTMOGUL_",)
    ),
    _source(Source.AIRWALLEX, "Airwallex", IN_CLI, npm=("airwallex-payment-elements",), env=("^AIRWALLEX_",)),
    _source(
        Source.FLUTTERWAVE,
        "Flutterwave",
        IN_CLI,
        npm=("flutterwave-node-v3",),
        pypi=("flutterwave",),
        env=("^FLUTTERWAVE_", "^FLW_(PUBLIC|SECRET)_KEY$"),
    ),
    _source(
        Source.DODOPAYMENTS,
        "Dodo Payments",
        IN_CLI,
        npm=("dodopayments",),
        pypi=("dodopayments",),
        env=("^DODO_PAYMENTS_",),
    ),
    _source(Source.WHOP, "Whop", IN_CLI, npm=("@whop/api", "@whop-apps/sdk"), env=("^WHOP_",)),
    # ---- Email / marketing ----
    _source(Source.SPARKPOST, "SparkPost", IN_CLI, npm=("sparkpost",), pypi=("sparkpost",), env=("^SPARKPOST_",)),
    _source(Source.MAILERSEND, "MailerSend", IN_CLI, npm=("mailersend",), pypi=("mailersend",), env=("^MAILERSEND_",)),
    _source(Source.ITERABLE, "Iterable", IN_CLI, env=("^ITERABLE_",)),
    _source(Source.CONVERTKIT, "ConvertKit", IN_CLI, env=("^CONVERTKIT_",)),
    _source(Source.DRIP, "Drip", IN_CLI, npm=("drip-nodejs",), env=("^DRIP_",)),
    _source(Source.OMNISEND, "Omnisend", IN_CLI, env=("^OMNISEND_",)),
    _source(Source.EMAILOCTOPUS, "EmailOctopus", IN_CLI, env=("^EMAILOCTOPUS_", "^EMAIL_OCTOPUS_")),
    _source(Source.ELASTICEMAIL, "Elastic Email", IN_CLI, env=("^ELASTICEMAIL_", "^ELASTIC_EMAIL_")),
    _source(
        Source.CAMPAIGNMONITOR,
        "Campaign Monitor",
        IN_CLI,
        npm=("createsend-node",),
        env=("^CAMPAIGN_MONITOR_", "^CREATESEND_"),
    ),
    _source(Source.LEMLIST, "Lemlist", IN_CLI, env=("^LEMLIST_",)),
    _source(Source.LOOPS, "Loops", IN_CLI, npm=("loops",), env=("^LOOPS_",)),
    _source(
        Source.KNOCK,
        "Knock",
        IN_CLI,
        npm=("@knocklabs/node", "@knocklabs/client"),
        pypi=("knockapi",),
        env=("^KNOCK_",),
    ),
    # A bare /^AWS_/ would fire on every AWS project, so we match only
    # the SES-specific prefix.
    _source(
        Source.AWSSES, "Amazon SES", IN_CLI, npm=("@aws-sdk/client-ses", "@aws-sdk/client-sesv2"), env=("^AWS_SES_",)
    ),
    _source(Source.BEEHIIV, "beehiiv", IN_CLI, env=("^BEEHIIV_",)),
    _source(Source.MAILTRAP, "Mailtrap", IN_CLI, npm=("mailtrap",), pypi=("mailtrap",), env=("^MAILTRAP_",)),
    _source(Source.PLUNK, "Plunk", IN_CLI, npm=("@plunk/node",), env=("^PLUNK_",)),
    _source(Source.ORTTO, "Ortto", IN_CLI, env=("^ORTTO_",)),
    _source(Source.POSTSCRIPT, "Postscript", IN_CLI, env=("^POSTSCRIPT_",)),
    _source(Source.MARKETO, "Marketo", IN_CLI, pypi=("marketorestpython",), env=("^MARKETO_",)),
    _source(Source.LOB, "Lob", IN_CLI, npm=("lob",), pypi=("lob",), env=("^LOB_API_KEY$",)),
    # ---- Product analytics / CDP ----
    _source(
        Source.SEGMENT,
        "Segment",
        IN_CLI,
        npm=("@segment/analytics-node", "analytics-node"),
        pypi=("segment-analytics-python", "analytics-python"),
        env=("^SEGMENT_",),
        competes_with=(ProductKey.PIPELINE_DESTINATIONS,),
    ),
    _source(
        Source.SNOWPLOW,
        "Snowplow Analytics",
        IN_CLI,
        npm=("@snowplow/node-tracker",),
        pypi=("snowplow-tracker",),
        env=("^SNOWPLOW_",),
        competes_with=(ProductKey.PRODUCT_ANALYTICS,),
    ),
    _source(
        Source.MATOMO,
        "Matomo",
        IN_CLI,
        npm=("matomo-tracker",),
        env=("^MATOMO_",),
        competes_with=(ProductKey.WEB_ANALYTICS,),
    ),
    _source(
        Source.PLAUSIBLE,
        "Plausible",
        IN_CLI,
        npm=("plausible-tracker",),
        env=("^PLAUSIBLE_",),
        competes_with=(ProductKey.WEB_ANALYTICS,),
    ),
    _source(Source.HEAP, "Heap", DEEP_LINK, env=("^HEAP_",), competes_with=(ProductKey.PRODUCT_ANALYTICS,)),
    _source(
        Source.LOGROCKET,
        "LogRocket",
        DEEP_LINK,
        npm=("logrocket", "logrocket-react", "@logrocket/react-native"),
        env=("^LOGROCKET_",),
        competes_with=(ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING),
    ),
    _competitor(
        "Hotjar",
        "Hotjar",
        npm=("@hotjar/browser", "react-hotjar"),
        env=("^HOTJAR_",),
        competes_with=(ProductKey.SESSION_REPLAY, ProductKey.HEATMAPS, ProductKey.SURVEYS),
    ),
    _source(
        Source.RUDDERSTACK,
        "RudderStack",
        DEEP_LINK,
        npm=("@rudderstack/analytics-js", "@rudderstack/rudder-sdk-node", "rudder-sdk-js"),
        pypi=("rudder-sdk-python",),
        env=("^RUDDERSTACK_",),
        competes_with=(ProductKey.PIPELINE_DESTINATIONS,),
    ),
    # ---- Feature flags / experimentation ----
    _source(
        Source.CONFIGCAT,
        "ConfigCat",
        IN_CLI,
        npm=("configcat-node", "configcat-js"),
        pypi=("configcat-client",),
        env=("^CONFIGCAT_",),
        competes_with=(ProductKey.FEATURE_FLAGS,),
    ),
    _source(
        Source.FLAGSMITH,
        "Flagsmith",
        IN_CLI,
        npm=("flagsmith-nodejs", "flagsmith"),
        pypi=("flagsmith",),
        env=("^FLAGSMITH_",),
        competes_with=(ProductKey.FEATURE_FLAGS,),
    ),
    _source(
        Source.UNLEASH,
        "Unleash",
        IN_CLI,
        npm=("unleash-client",),
        pypi=("unleashclient",),
        env=("^UNLEASH_",),
        competes_with=(ProductKey.FEATURE_FLAGS,),
    ),
    _source(
        Source.SPLITIO,
        "Split.io",
        IN_CLI,
        npm=("@splitsoftware/splitio",),
        pypi=("splitio-client",),
        env=("^SPLITIO_", "^SPLIT_IO_"),
        competes_with=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    ),
    _source(
        Source.STATSIG,
        "Statsig",
        DEEP_LINK,
        npm=("statsig-js", "statsig-node", "@statsig/js-client", "@statsig/react-bindings"),
        pypi=("statsig",),
        rubygems=("statsig",),
        env=("^STATSIG_",),
        competes_with=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    ),
    _source(
        Source.GROWTHBOOK,
        "GrowthBook",
        DEEP_LINK,
        npm=("@growthbook/growthbook", "@growthbook/growthbook-react"),
        pypi=("growthbook",),
        rubygems=("growthbook",),
        env=("^GROWTHBOOK_",),
        competes_with=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    ),
    # ---- Auth / secrets ----
    _source(Source.STYTCH, "Stytch", IN_CLI, npm=("stytch",), pypi=("stytch",), env=("^STYTCH_",)),
    _source(Source.DOPPLER, "Doppler", IN_CLI, npm=("@dopplerhq/node-sdk",), env=("^DOPPLER_",)),
    _source(
        Source.INFISICAL, "Infisical", IN_CLI, npm=("@infisical/sdk",), pypi=("infisicalsdk",), env=("^INFISICAL_",)
    ),
    _source(
        Source.ONEPASSWORD,
        "1Password",
        IN_CLI,
        npm=("@1password/sdk",),
        pypi=("onepassword-sdk",),
        env=("^ONEPASSWORD_", "^OP_SERVICE_ACCOUNT_TOKEN$"),
    ),
    _source(Source.PERSONA, "Persona", IN_CLI, env=("^PERSONA_",)),
    # ---- Comms / webhooks / voice ----
    _source(Source.SVIX, "Svix", IN_CLI, npm=("svix",), pypi=("svix",), env=("^SVIX_",)),
    _source(Source.MUX, "Mux", IN_CLI, npm=("@mux/mux-node",), pypi=("mux-python",), env=("^MUX_",)),
    _source(Source.VAPI, "Vapi", IN_CLI, npm=("@vapi-ai/server-sdk",), pypi=("vapi-server-sdk",), env=("^VAPI_",)),
    _source(Source.AIRCALL, "Aircall", IN_CLI, env=("^AIRCALL_",)),
    _source(Source.JUSTCALL, "JustCall", IN_CLI, env=("^JUSTCALL_",)),
    _source(Source.TELNYX, "Telnyx", IN_CLI, npm=("telnyx",), pypi=("telnyx",), env=("^TELNYX_",)),
    _source(Source.PLIVO, "Plivo", IN_CLI, npm=("plivo",), pypi=("plivo",), env=("^PLIVO_",)),
    # COURIER_ is a generic shipping word, so we match the exact key.
    _source(
        Source.COURIER,
        "Courier",
        IN_CLI,
        npm=("@trycourier/courier",),
        pypi=("trycourier",),
        env=("^COURIER_AUTH_TOKEN$",),
    ),
    # ---- E-commerce / logistics ----
    _source(
        Source.WOOCOMMERCE,
        "WooCommerce",
        IN_CLI,
        npm=("@woocommerce/woocommerce-rest-api",),
        pypi=("woocommerce",),
        env=("^WOOCOMMERCE_",),
    ),
    _source(Source.RECHARGE, "Recharge", IN_CLI, env=("^RECHARGE_",)),
    _source(
        Source.COMMERCETOOLS,
        "commercetools",
        IN_CLI,
        npm=("@commercetools/platform-sdk",),
        pypi=("commercetools",),
        env=("^CTP_", "^COMMERCETOOLS_"),
    ),
    _source(Source.WEBFLOW, "Webflow", IN_CLI, npm=("webflow-api",), env=("^WEBFLOW_",)),
    _source(Source.EASYPOST, "EasyPost", IN_CLI, npm=("@easypost/api",), pypi=("easypost",), env=("^EASYPOST_",)),
    _source(Source.SHIPPO, "Shippo", IN_CLI, npm=("shippo",), pypi=("shippo",), env=("^SHIPPO_",)),
    _source(Source.SHIPSTATION, "ShipStation", IN_CLI, env=("^SHIPSTATION_",)),
    _source(Source.SQUARESPACE, "Squarespace", IN_CLI, env=("^SQUARESPACE_",)),
    _source(Source.PRINTIFY, "Printify", IN_CLI, env=("^PRINTIFY_",)),
    _source(Source.BIGCOMMERCE, "BigCommerce", IN_CLI, npm=("node-bigcommerce",), env=("^BIGCOMMERCE_",)),
    # ---- Support / helpdesk ----
    _source(Source.FRESHDESK, "Freshdesk", IN_CLI, pypi=("python-freshdesk",), env=("^FRESHDESK_",)),
    _source(Source.FRONT, "Front", IN_CLI, env=("^FRONTAPP_", "^FRONT_API_")),
    _source(Source.GORGIAS, "Gorgias", IN_CLI, env=("^GORGIAS_",)),
    _source(Source.CHATWOOT, "Chatwoot", IN_CLI, env=("^CHATWOOT_",)),
    _source(Source.KUSTOMER, "Kustomer", IN_CLI, env=("^KUSTOMER_",)),
    _source(Source.PLAIN, "Plain", IN_CLI, npm=("@team-plain/typescript-sdk",), env=("^PLAIN_",)),
    _source(Source.CANNY, "Canny", IN_CLI, env=("^CANNY_",)),
    _source(Source.PYLON, "Pylon", IN_CLI, env=("^PYLON_",)),
    # ---- Dev / infra / observability ----
    _source(
        Source.GITLAB,
        "GitLab",
        IN_CLI,
        npm=("@gitbeaker/rest",),
        pypi=("python-gitlab",),
        rubygems=("gitlab",),
        env=("^GITLAB_",),
    ),
    _source(Source.BITBUCKET, "Atlassian Bitbucket Cloud", IN_CLI, npm=("bitbucket",), env=("^BITBUCKET_",)),
    _source(Source.GITEA, "Gitea", IN_CLI, npm=("gitea-js",), env=("^GITEA_",)),
    _source(
        Source.DATADOG,
        "Datadog",
        IN_CLI,
        npm=("@datadog/datadog-api-client", "dd-trace"),
        pypi=("datadog", "datadog-api-client"),
        rubygems=("dogapi",),
        env=("^DATADOG_", "^DD_API_KEY$", "^DD_APP_KEY$"),
        competes_with=(ProductKey.LOGS, ProductKey.TRACING, ProductKey.ERROR_TRACKING),
    ),
    _source(
        Source.NEWRELIC,
        "New Relic",
        IN_CLI,
        npm=("newrelic",),
        pypi=("newrelic",),
        rubygems=("newrelic_rpm",),
        env=("^NEW_RELIC_", "^NEWRELIC_"),
        competes_with=(ProductKey.LOGS, ProductKey.TRACING),
    ),
    _source(
        Source.CLOUDFLARE,
        "Cloudflare",
        IN_CLI,
        npm=("cloudflare",),
        pypi=("cloudflare",),
        env=("^CLOUDFLARE_", "^CF_API_TOKEN$"),
    ),
    _source(
        Source.ELASTICSEARCH,
        "Elasticsearch",
        IN_CLI,
        npm=("@elastic/elasticsearch",),
        pypi=("elasticsearch",),
        rubygems=("elasticsearch",),
        env=("^ELASTICSEARCH_",),
    ),
    _source(Source.SNYK, "Snyk", IN_CLI, npm=("snyk",), pypi=("pysnyk",), env=("^SNYK_",)),
    _source(
        Source.PAGERDUTY,
        "PagerDuty",
        IN_CLI,
        npm=("@pagerduty/pdjs",),
        pypi=("pdpyras",),
        env=("^PAGERDUTY_", "^PD_API_KEY$"),
    ),
    _source(Source.OPSGENIE, "Opsgenie", IN_CLI, env=("^OPSGENIE_",)),
    _source(Source.INCIDENTIO, "incident.io", IN_CLI, env=("^INCIDENT_IO_", "^INCIDENTIO_")),
    _source(
        Source.BUGSNAG,
        "Bugsnag",
        IN_CLI,
        npm=("@bugsnag/js",),
        pypi=("bugsnag",),
        rubygems=("bugsnag",),
        env=("^BUGSNAG_",),
        competes_with=(ProductKey.ERROR_TRACKING,),
    ),
    _source(
        Source.HONEYBADGER,
        "Honeybadger",
        IN_CLI,
        npm=("@honeybadger-io/js",),
        pypi=("honeybadger",),
        rubygems=("honeybadger",),
        env=("^HONEYBADGER_",),
        competes_with=(ProductKey.ERROR_TRACKING,),
    ),
    _source(
        Source.RAYGUN,
        "Raygun",
        IN_CLI,
        npm=("raygun",),
        pypi=("raygun4py",),
        rubygems=("raygun4ruby",),
        env=("^RAYGUN_",),
        competes_with=(ProductKey.ERROR_TRACKING,),
    ),
    _source(Source.CIRCLECI, "CircleCI", IN_CLI, env=("^CIRCLECI_", "^CIRCLE_TOKEN$")),
    _source(Source.UPSTASH, "Upstash", IN_CLI, npm=("@upstash/redis",), pypi=("upstash-redis",), env=("^UPSTASH_",)),
    _source(Source.VERCEL, "Vercel", IN_CLI, npm=("@vercel/sdk",), env=("^VERCEL_API_TOKEN$",)),
    _source(
        Source.ALGOLIA,
        "Algolia",
        IN_CLI,
        npm=("algoliasearch",),
        pypi=("algoliasearch",),
        rubygems=("algolia",),
        env=("^ALGOLIA_",),
    ),
    _source(Source.INNGEST, "Inngest", IN_CLI, npm=("inngest",), pypi=("inngest",), env=("^INNGEST_",)),
    # TRIGGER_ alone is a common app-domain prefix, so we match only the
    # three keys Trigger.dev actually documents.
    _source(
        Source.TRIGGERDEV,
        "Trigger.dev",
        IN_CLI,
        npm=("@trigger.dev/sdk",),
        env=("^TRIGGER_(SECRET_KEY|API_KEY|PROJECT_ID)$",),
    ),
    _source(Source.ABLY, "Ably", IN_CLI, npm=("ably",), pypi=("ably",), env=("^ABLY_",)),
    _source(Source.NETLIFY, "Netlify", IN_CLI, npm=("@netlify/functions",), env=("^NETLIFY_",)),
    _source(Source.RAILWAY, "Railway", IN_CLI, env=("^RAILWAY_",)),
    # RENDER_ is a generic word in front-end code - exact key only.
    _source(Source.RENDER, "Render", IN_CLI, env=("^RENDER_API_KEY$",)),
    # `fly.toml` is not one of the manifests we read, so env keys are the
    # only signal available.
    _source(Source.FLYIO, "Fly.io", IN_CLI, env=("^FLY_API_TOKEN$", "^FLY_APP_NAME$")),
    _source(Source.HEROKU, "Heroku", IN_CLI, env=("^HEROKU_",)),
    # DO_ is too short to be safe, so we match the full product name.
    _source(Source.DIGITALOCEAN, "DigitalOcean", IN_CLI, env=("^DIGITALOCEAN_",)),
    _source(Source.GRAFANA, "Grafana", IN_CLI, pypi=("grafana-client",), env=("^GRAFANA_",)),
    # Logtail is Better Stack's log product - same account, same source.
    _source(
        Source.BETTERSTACK,
        "Better Stack",
        IN_CLI,
        npm=("@logtail/node", "@logtail/js"),
        env=("^BETTERSTACK_", "^BETTER_STACK_", "^LOGTAIL_"),
        competes_with=(ProductKey.LOGS,),
    ),
    _source(
        Source.HONEYCOMB,
        "Honeycomb",
        IN_CLI,
        npm=("@honeycombio/opentelemetry-node", "honeycomb-beeline"),
        pypi=("honeycomb-beeline", "libhoney"),
        env=("^HONEYCOMB_",),
        competes_with=(ProductKey.TRACING,),
    ),
    _source(
        Source.DESCOPE,
        "Descope",
        IN_CLI,
        npm=("@descope/node-sdk", "@descope/nextjs-sdk", "@descope/react-sdk"),
        pypi=("descope",),
        env=("^DESCOPE_",),
    ),
    _source(
        Source.FUSIONAUTH,
        "FusionAuth",
        IN_CLI,
        npm=("@fusionauth/typescript-client",),
        pypi=("fusionauth-client",),
        env=("^FUSIONAUTH_", "^FUSION_AUTH_"),
    ),
    _source(Source.HOOKDECK, "Hookdeck", IN_CLI, npm=("@hookdeck/sdk",), env=("^HOOKDECK_",)),
    _source(Source.N8N, "n8n", IN_CLI, npm=("n8n",), env=("^N8N_",)),
    # NOTE: these signals prove the project uses dbt, not that it uses dbt
    # Cloud - the source needs dbt Cloud credentials. Local-only dbt users
    # are a known false positive.
    _source(
        Source.DBT,
        "dbt",
        IN_CLI,
        pypi=("dbt-core", "dbt-snowflake", "dbt-postgres", "dbt-bigquery", "dbt-redshift", "dbt-databricks"),
        env=("^DBT_",),
    ),
    _source(Source.FASTLY, "Fastly", IN_CLI, npm=("fastly",), pypi=("fastly",), env=("^FASTLY_",)),
    _source(Source.BUNNY, "Bunny.net", IN_CLI, env=("^BUNNY_",)),
    _source(Source.CODECOV, "Codecov", IN_CLI, npm=("codecov",), env=("^CODECOV_",)),
    _source(Source.SOURCEGRAPH, "Sourcegraph", IN_CLI, env=("^SOURCEGRAPH_", "^SRC_ACCESS_TOKEN$")),
    # NOTE: these signals also match a self-hosted Temporal cluster, but the
    # source wants Temporal Cloud mTLS certificates.
    _source(
        Source.TEMPORALIO,
        "Temporal.io",
        IN_CLI,
        npm=("@temporalio/client", "@temporalio/worker"),
        pypi=("temporalio",),
        env=("^TEMPORAL_",),
    ),
    _source(
        Source.HATCHET,
        "Hatchet",
        IN_CLI,
        npm=("@hatchet-dev/typescript-sdk",),
        pypi=("hatchet-sdk",),
        env=("^HATCHET_",),
    ),
    # ---- CRM / sales ----
    _source(Source.PIPEDRIVE, "Pipedrive", IN_CLI, npm=("pipedrive",), env=("^PIPEDRIVE_",)),
    _source(Source.CLOSE, "Close", IN_CLI, pypi=("closeio",), env=("^CLOSE_API_KEY$",)),
    _source(Source.COPPER, "Copper", IN_CLI, env=("^COPPER_",)),
    _source(Source.INSIGHTLY, "Insightly", IN_CLI, env=("^INSIGHTLY_",)),
    _source(Source.SALESFLARE, "Salesflare", IN_CLI, env=("^SALESFLARE_",)),
    _source(Source.SALESLOFT, "Salesloft", IN_CLI, env=("^SALESLOFT_",)),
    _source(Source.ATTIO, "Attio", IN_CLI, npm=("attio",), env=("^ATTIO_",)),
    _source(Source.ACTIVECAMPAIGN, "ActiveCampaign", IN_CLI, env=("^ACTIVECAMPAIGN_", "^ACTIVE_CAMPAIGN_")),
    _source(Source.VITALLY, "Vitally", IN_CLI, env=("^VITALLY_",)),
    _source(
        Source.DOCUSIGN, "DocuSign", IN_CLI, npm=("docusign-esign",), pypi=("docusign-esign",), env=("^DOCUSIGN_",)
    ),
    _source(Source.PANDADOC, "PandaDoc", IN_CLI, env=("^PANDADOC_",)),
    _source(Source.GONG, "Gong", IN_CLI, env=("^GONG_",)),
    # ---- PM / productivity ----
    _source(Source.ASANA, "Asana", IN_CLI, npm=("asana",), pypi=("asana",), env=("^ASANA_",)),
    _source(Source.TRELLO, "Trello", IN_CLI, npm=("trello",), env=("^TRELLO_",)),
    _source(
        Source.TODOIST,
        "Todoist",
        IN_CLI,
        npm=("@doist/todoist-api-typescript",),
        pypi=("todoist-api-python",),
        env=("^TODOIST_",),
    ),
    _source(Source.MONDAY, "monday.com", IN_CLI, npm=("@mondaydotcomorg/api",), env=("^MONDAY_",)),
    _source(Source.CLICKUP, "ClickUp", IN_CLI, env=("^CLICKUP_",)),
    _source(Source.HEIGHT, "Height", IN_CLI, env=("^HEIGHT_API_KEY$",)),
    _source(Source.SHORTCUT, "Shortcut", IN_CLI, npm=("@shortcut/client",), env=("^SHORTCUT_",)),
    _source(Source.JIRA, "Jira", IN_CLI, npm=("jira-client",), pypi=("jira", "atlassian-python-api"), env=("^JIRA_",)),
    _source(Source.CONFLUENCE, "Confluence", IN_CLI, env=("^CONFLUENCE_",)),
    _source(Source.AIRTABLE, "Airtable", IN_CLI, npm=("airtable",), pypi=("pyairtable",), env=("^AIRTABLE_",)),
    _source(
        Source.SMARTSHEET,
        "Smartsheet",
        IN_CLI,
        npm=("smartsheet",),
        pypi=("smartsheet-python-sdk",),
        env=("^SMARTSHEET_",),
    ),
    _source(Source.CODA, "Coda", IN_CLI, env=("^CODA_API_",)),
    _source(Source.PRODUCTBOARD, "Productboard", IN_CLI, env=("^PRODUCTBOARD_",)),
    _source(
        Source.GOOGLESHEETS,
        "Google Sheets",
        IN_CLI,
        npm=("google-spreadsheet",),
        pypi=("gspread",),
        env=("^GOOGLE_SHEETS_",),
    ),
    _source(Source.FORMBRICKS, "Formbricks", IN_CLI, npm=("@formbricks/js",), env=("^FORMBRICKS_",)),
    # Tally is also an accounting product, so we match the exact key.
    _source(Source.TALLY, "Tally", IN_CLI, env=("^TALLY_API_KEY$",)),
    _source(Source.JOTFORM, "Jotform", IN_CLI, pypi=("jotform",), env=("^JOTFORM_",)),
    _source(Source.GITBOOK, "GitBook", IN_CLI, npm=("@gitbook/api",), env=("^GITBOOK_",)),
    # NOTE: recall is low here. Most WordPress projects are PHP, and
    # `composer.json` is not one of the manifests we read.
    _source(Source.WORDPRESS, "WordPress", IN_CLI, npm=("wpapi",), env=("^WORDPRESS_",)),
    _source(Source.CLOCKIFY, "Clockify", IN_CLI, env=("^CLOCKIFY_",)),
    # ---- Scheduling / events ----
    _source(Source.CALENDLY, "Calendly", IN_CLI, env=("^CALENDLY_",)),
    _source(Source.CALCOM, "Cal.com", IN_CLI, env=("^CALCOM_", "^CAL_API_KEY$")),
    _source(Source.EVENTBRITE, "Eventbrite", IN_CLI, pypi=("eventbrite",), env=("^EVENTBRITE_",)),
    # ---- HR / people ----
    _source(Source.BAMBOOHR, "BambooHR", IN_CLI, pypi=("pybamboohr",), env=("^BAMBOOHR_", "^BAMBOO_HR_")),
    _source(Source.PERSONIO, "Personio", IN_CLI, env=("^PERSONIO_",)),
    _source(Source.RIPPLING, "Rippling", IN_CLI, env=("^RIPPLING_",)),
    _source(Source.GREENHOUSE, "Greenhouse", IN_CLI, env=("^GREENHOUSE_",)),
    _source(Source.ASHBY, "Ashby", IN_CLI, env=("^ASHBY_",)),
    _source(Source.WORKABLE, "Workable", IN_CLI, env=("^WORKABLE_",)),
    # ---- Ads / marketing analytics (OAuth-first -> deep-link) ----
    _source(
        Source.GOOGLEADS, "Google Ads", DEEP_LINK, npm=("google-ads-api",), pypi=("google-ads",), env=("^GOOGLE_ADS_",)
    ),
    _source(
        Source.METAADS,
        "Meta Ads",
        DEEP_LINK,
        npm=("facebook-nodejs-business-sdk",),
        pypi=("facebook-business",),
        env=("^META_ADS_", "^FACEBOOK_ADS_"),
    ),
    _source(Source.LINKEDINADS, "LinkedIn Ads", DEEP_LINK, env=("^LINKEDIN_ADS_",)),
    _source(Source.TIKTOKADS, "TikTok Ads", DEEP_LINK, env=("^TIKTOK_ADS_",)),
    _source(Source.REDDITADS, "Reddit Ads", DEEP_LINK, env=("^REDDIT_ADS_",)),
    _source(Source.PINTERESTADS, "Pinterest Ads", DEEP_LINK, env=("^PINTEREST_ADS_",)),
    _source(Source.BINGADS, "Bing Ads", DEEP_LINK, pypi=("bingads",), env=("^BING_ADS_", "^MICROSOFT_ADS_")),
    _source(Source.AMAZONADS, "Amazon Ads", DEEP_LINK, env=("^AMAZON_ADS_",)),
    _source(
        Source.GOOGLEANALYTICS,
        "Google Analytics",
        DEEP_LINK,
        npm=("react-ga4",),
        pypi=("google-analytics-data",),
        env=("^GOOGLE_ANALYTICS_", "^GA4_"),
        competes_with=(ProductKey.WEB_ANALYTICS,),
    ),
    _source(Source.GOOGLESEARCHCONSOLE, "Google Search Console", DEEP_LINK, env=("^SEARCH_CONSOLE_", "^GSC_")),
    _source(Source.APPSFLYER, "AppsFlyer", IN_CLI, npm=("react-native-appsflyer",), env=("^APPSFLYER_",)),
    _source(Source.DUB, "Dub", IN_CLI, npm=("dub",), pypi=("dub",), env=("^DUB_API_KEY$",)),
)
