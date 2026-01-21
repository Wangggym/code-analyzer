"""Request schemas"""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Request model for code analysis"""

    problem_description: str = Field(
        ...,
        description="Natural language description of the features to analyze",
        examples=["Create a multi-channel forum api with channel and message models"],
    )

    class Config:
        json_schema_extra = {
            "example": {
                "problem_description": "Create a multi-channel forum api. "
                "Channel Model: { id, name }. "
                "Message Model: { id, title, content, channel, createdAt }. "
                "The API should have these features: create a channel, "
                "write messages in a channel, list messages in a channel."
            }
        }
