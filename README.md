# Code Analyzer

AI-powered code analysis agent that analyzes code repositories and generates structured feature location reports with optional functional verification.

## Features

- **Code Analysis**: Analyzes code to locate feature implementations (file, function, line numbers)
- **Multi-LLM Support**: Uses Claude 4.5 (primary) and GPT-4o mini (lightweight)
- **Functional Verification**: Dynamically generates and executes tests in isolated Docker containers
- **SSE Streaming**: Real-time progress updates for long-running operations
- **Structured Output**: JSON reports with precise implementation locations

## Quick Start

### Prerequisites

- Docker & Docker Compose
- LLM API keys (Anthropic Claude / OpenAI)

### Run with Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/user/code-analyzer.git
cd code-analyzer

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Build and run
docker build -t code-analyzer .
docker run -d \
  --name code-analyzer \
  -p 3006:3006 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env-file .env \
  code-analyzer

# 4. Verify it's running
curl http://localhost:3006/health
```

### Test the API

```bash
# Prepare test data
zip -r test-project.zip your-project-folder/

# Basic analysis (fast, no verification)
curl -X POST http://localhost:3006/analyze \
  -F "problem_description=Describe the features to locate..." \
  -F "code_zip=@test-project.zip" \
  -F "run_verification=false"

# Full analysis with functional verification (SSE streaming)
curl -X POST http://localhost:3006/analyze/stream \
  -F "problem_description=Describe the features to locate..." \
  -F "code_zip=@test-project.zip" \
  --no-buffer
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/analyze` | Analyze code (optional verification) |
| POST | `/analyze/stream` | Analyze with SSE streaming (always runs verification) |

## Request Format

**Content-Type**: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `problem_description` | string | Yes | Natural language description of features to locate |
| `code_zip` | file | Yes | ZIP file containing the source code |
| `run_verification` | boolean | No | Run functional verification (default: false, only for `/analyze`) |

## Response Format

### `/analyze` Response

```json
{
  "feature_analysis": [
    {
      "feature_description": "Create a channel",
      "implementation_location": [
        {
          "file": "src/channel/channel.service.ts",
          "function": "create",
          "lines": "21-24"
        }
      ]
    }
  ],
  "execution_plan_suggestion": "npm install && npm run start",
  "functional_verification": {
    "generated_test_code": "const BASE_URL = ...",
    "execution_result": {
      "tests_passed": true,
      "log": "All tests passed"
    }
  }
}
```

### `/analyze/stream` SSE Events

```
data: {"stage": "extracting", "message": "Extracting code archive..."}
data: {"stage": "analyzing_code", "message": "Analyzing code structure with AI..."}
data: {"stage": "analyzing_startup", "message": "Analyzing how to start the project..."}
data: {"stage": "starting_project", "message": "Starting project in Docker sandbox..."}
data: {"stage": "waiting_health", "message": "Waiting for service to be ready..."}
data: {"stage": "generating_tests", "message": "Generating test code with AI..."}
data: {"stage": "running_tests", "message": "Executing tests..."}
data: {"stage": "cleanup", "message": "Stopping project and cleaning up..."}
data: {"stage": "complete", "message": "Analysis complete", "data": {...full result...}}
```

## Configuration

### Environment Variables

```bash
# LLM Configuration (required)
ANTHROPIC_API_KEY=your-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com    # or proxy URL
ANTHROPIC_MODEL_ID=claude-sonnet-4-20250514

OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1       # or proxy URL
OPENAI_MODEL_ID=gpt-4o-mini

# Application Settings (optional)
DEBUG=false
APP_PORT=3006
LOG_LEVEL=INFO

# Sandbox Settings (optional)
SANDBOX_TIMEOUT=300
SANDBOX_MEMORY_LIMIT=512m
SANDBOX_CPU_LIMIT=1.0
```

## How It Works

```
1. Upload ZIP ──> 2. Extract ──> 3. LLM Analyze Code ──> 4. Generate Report
                                         │
                                         ▼ (if verification enabled)
                                 5. LLM Analyze Startup Method
                                         │
                                         ▼
                                 6. Start Project in Docker
                                    (docker run node:20 "npm install && npm start")
                                         │
                                         ▼
                                 7. LLM Generate Tests
                                         │
                                         ▼
                                 8. Execute Tests ──> 9. Cleanup ──> 10. Return Results
```

### Key Design Decisions

1. **Startup Analysis**: LLM reads `README.md`, `package.json`, etc. to determine the simplest way to start the project (prefers `npm start` over `docker-compose`)

2. **Docker Sandbox**: All projects run in isolated Docker containers (`node:20`, `python:3.12`, etc.) for security

3. **SSE Streaming**: Long operations (2-3 minutes) use Server-Sent Events for real-time progress

## Development

### Local Development (without Docker)

```bash
# Prerequisites: Python 3.12+, uv package manager

# Install dependencies
make gen

# Run development server
make dev

# Run linter
make lint

# Run tests
make test
```

### Project Structure

```
src/
├── main.py                 # FastAPI application entry
├── config/                 # Configuration management
├── rest/                   # API endpoints
│   └── analyze.py          # /analyze and /analyze/stream
├── schema/                 # Request/Response models
├── services/
│   ├── zip_handler.py      # ZIP extraction
│   ├── code_parser.py      # Code structure parsing
│   ├── llm_analyzer.py     # LLM code analysis
│   ├── startup_analyzer.py # LLM startup method analysis
│   ├── report_generator.py # Report generation
│   ├── sse_helper.py       # SSE utilities
│   └── sandbox/
│       ├── project_runner.py  # Docker container management
│       └── test_runner.py     # Test generation & execution
└── util/                   # Utilities
```

## License

MIT
