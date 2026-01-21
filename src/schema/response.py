"""Response schemas"""

from pydantic import BaseModel, Field


class ImplementationLocation(BaseModel):
    """Location of a feature implementation in code"""

    file: str = Field(..., description="File path relative to project root")
    function: str = Field(..., description="Function or method name")
    lines: str = Field(..., description="Line range, e.g., '13-16'")


class FeatureAnalysis(BaseModel):
    """Analysis of a single feature"""

    feature_description: str = Field(..., description="Description of the feature")
    implementation_location: list[ImplementationLocation] = Field(
        default_factory=list,
        description="List of code locations implementing this feature",
    )


class ExecutionResult(BaseModel):
    """Result of test execution"""

    tests_passed: bool = Field(..., description="Whether all tests passed")
    log: str = Field(..., description="Execution log output")


class FunctionalVerification(BaseModel):
    """Functional verification with generated tests"""

    generated_test_code: str = Field(..., description="Generated test code")
    execution_result: ExecutionResult = Field(..., description="Test execution result")


class AnalyzeResponse(BaseModel):
    """Response model for code analysis"""

    feature_analysis: list[FeatureAnalysis] = Field(
        default_factory=list,
        description="List of analyzed features with their implementation locations",
    )
    execution_plan_suggestion: str = Field(
        default="",
        description="Suggestion on how to run the project",
    )
    functional_verification: FunctionalVerification | None = Field(
        default=None,
        description="Optional functional verification with generated tests",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "feature_analysis": [
                    {
                        "feature_description": "Create a channel",
                        "implementation_location": [
                            {
                                "file": "src/modules/channel/channel.resolver.ts",
                                "function": "createChannel",
                                "lines": "13-16",
                            },
                            {
                                "file": "src/modules/channel/channel.service.ts",
                                "function": "create",
                                "lines": "21-24",
                            },
                        ],
                    }
                ],
                "execution_plan_suggestion": "Run npm install && npm run start:dev",
                "functional_verification": {
                    "generated_test_code": "describe('API', () => { ... });",
                    "execution_result": {"tests_passed": True, "log": "1 passing"},
                },
            }
        }
