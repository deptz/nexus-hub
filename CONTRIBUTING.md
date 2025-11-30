# Contributing to Nexus Hub

Thank you for your interest in contributing to Nexus Hub! This document provides guidelines and instructions for contributing.

## Getting Started

### Prerequisites

- Python 3.11+ (recommended for latest package versions)
- PostgreSQL 15+ with `pgvector` extension
- Git

### Development Setup

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/deptz/nexus-hub.git
   cd nexus-hub
   ```

2. **Create a virtual environment**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   # or
   venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Set up the database**
   ```bash
   createdb nexus_hub
   psql -d nexus_hub -f migrations/001_initial_schema.sql
   psql -d nexus_hub -f migrations/002_enable_rls.sql
   ```

5. **Create environment file**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

6. **Start the development server**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## Code Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use type hints where appropriate
- Keep functions focused and single-purpose
- Write clear, descriptive variable and function names
- Add docstrings to all public functions and classes

### Formatting

We recommend using `black` for code formatting (if you have it installed):
```bash
black app/ tests/
```

## Testing

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_prompt_validator.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

### Writing Tests

- Write tests for all new features and bug fixes
- Follow the existing test structure in `tests/`
- Use descriptive test names that explain what is being tested
- Ensure tests are isolated and don't depend on external services (use mocks when needed)

### Test Database

For integration tests, use a separate test database:
```bash
createdb nexus_hub_test
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/nexus_hub_test
pytest tests/test_integration_e2e.py -v
```

## Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write code following the style guidelines
   - Add tests for your changes
   - Update documentation if needed

3. **Commit your changes**
   ```bash
   git add .
   git commit -m "Description of your changes"
   ```
   - Write clear, descriptive commit messages
   - Reference issue numbers if applicable (e.g., "Fix #123: Description")

4. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request**
   - Go to the repository on GitHub
   - Click "New Pull Request"
   - Select your branch
   - Fill out the PR template with:
     - Description of changes
     - Related issues (if any)
     - Testing instructions
     - Any breaking changes

6. **Respond to feedback**
   - Address review comments
   - Make requested changes
   - Keep the PR updated with the main branch

## Reporting Issues

### Bug Reports

When reporting bugs, please include:
- Clear description of the issue
- Steps to reproduce
- Expected behavior
- Actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or error messages

### Feature Requests

For feature requests, please include:
- Clear description of the feature
- Use case and motivation
- Proposed implementation approach (if you have ideas)

## Code Review Guidelines

- Be respectful and constructive in reviews
- Focus on code quality, not personal preferences
- Explain the reasoning behind suggestions
- Approve when the code is ready, or request changes with clear feedback

## Questions?

If you have questions about contributing, please:
- Open an issue with the `question` label
- Check existing documentation in `docs/` (see [docs/README.md](docs/README.md) for full index)
- Review the README.md for setup instructions

Thank you for contributing to Nexus Hub!

