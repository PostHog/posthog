from pydantic import BaseModel, Field


class RiskSignal(BaseModel):
    title: str = Field(description="Short risk title")
    explanation: str = Field(description="1-2 sentence explanation with data")


class Question(BaseModel):
    question: str = Field(description="Question with data context for the PR author")


class TasteObservation(BaseModel):
    observation: str = Field(description="Single observation about product taste")


class ProductReviewRaw(BaseModel):
    """Raw structured output from the write_summary step. Items may contain code references."""

    one_liner: str = Field(description="One sentence: what does this change for users, grounded in data")
    risk_signals: list[RiskSignal] = Field(default_factory=list, description="Risk signals worth flagging")
    questions: list[Question] = Field(description="1-3 pointed questions for the author")
    taste: list[TasteObservation] = Field(
        default_factory=list, description="Taste observations about consistency, defaults, affordances"
    )


class RewrittenItem(BaseModel):
    original: str = Field(description="The original text from the raw review")
    rewritten: str = Field(description="The item rewritten in product/user terms, no code identifiers")
    product_relevance: int = Field(
        description="Product relevance score 1-10. 10 = pure user impact, 1 = pure code/architecture nitpick",
        ge=1,
        le=10,
    )


class ProductReviewRewritten(BaseModel):
    """Output of the rewrite step. Items are in product language with relevance scores."""

    one_liner: str = Field(description="One-liner rewritten in product terms if needed")
    risk_signals: list[RewrittenItem] = Field(default_factory=list)
    questions: list[RewrittenItem] = Field(default_factory=list)
    taste: list[RewrittenItem] = Field(default_factory=list)
