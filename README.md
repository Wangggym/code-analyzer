# Code Analyzer

AI-powered code analyzer agent that analyzes code repositories and generates structured feature location reports.

## Features

- **Code Analysis**: Analyzes code repositories to locate feature implementations
- **Multi-LLM Support**: Uses Claude 4.5 (primary) and GPT-4o mini (lightweight)
- **Sandbox Execution**: Dynamically generates and executes tests in isolated Docker containers
- **Structured Output**: Generates JSON reports with precise file/function/line locations

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for sandbox execution)

### Installation

```bash
# Clone the repository
git clone https://github.com/user/code-analyzer.git
cd code-analyzer

# Install dependencies
make install

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Running

```bash
# Development mode
make run

# Or with Docker
make docker-build
make docker-run
```

### API Usage

```bash
# Analyze code
curl -X POST http://localhost:3006/analyze \
  -F "problem_description=@requirements.md" \
  -F "code_zip=@project.zip"
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/analyze` | Analyze code and generate report |

## Request Format

- `problem_description` (string): Natural language description of required features
- `code_zip` (file): ZIP file containing the source code

## Response Format

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
  "execution_plan_suggestion": "Run npm install && npm run start:dev",
  "functional_verification": {
    "generated_test_code": "...",
    "execution_result": {
      "tests_passed": true,
      "log": "..."
    }
  }
}
```

## Configuration

See `.env.example` for all available configuration options.

### LLM Configuration

Supports both official APIs and proxy endpoints:

```bash
# Official Anthropic API
ANTHROPIC_API_KEY=sk-ant-xxxx
ANTHROPIC_BASE_URL=https://api.anthropic.com

# Or Proxy API
ANTHROPIC_API_KEY=your-proxy-key
ANTHROPIC_BASE_URL=https://anthropic-proxy.example.com
```

## Development

```bash
# Install dev dependencies
make dev

# Run linter
make lint

# Format code
make format

# Run tests
make test
```

## Architecture

```
src/
├── main.py                 # FastAPI application entry
├── config/                 # Configuration management
├── rest/                   # API endpoints
├── schema/                 # Request/Response models
├── services/
│   ├── zip_handler.py      # ZIP extraction
│   ├── code_parser.py      # Code structure parsing
│   ├── llm_analyzer.py     # LLM analysis logic
│   ├── report_generator.py # Report generation
│   └── sandbox/            # Docker sandbox execution
└── util/                   # Utilities
```

## License

MIT
