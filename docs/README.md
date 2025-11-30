# Nexus Hub Documentation

Welcome to the Nexus Hub documentation. This index provides an organized view of all available documentation.

## 📚 Documentation Structure

### 🚀 Getting Started

- **[Kickstart Guide](guides/KICKSTART_GUIDE.md)** - Complete 5-minute setup guide with step-by-step instructions for local development and testing

### 📖 User Guides

- **[Telegram Setup](guides/TELEGRAM_SETUP.md)** - How to set up and configure the Telegram adapter for testing
- **[MCP Server Security](guides/MCP_SERVER_SECURITY.md)** - Security requirements and best practices for MCP server integration

### 🔧 Technical Documentation

- **[System Architecture](technical/SYSTEM_ARCHITECTURE.md)** - System design, architecture diagrams, component interactions, and data flow
- **[Agentic Message Flow](technical/AGENTIC_MESSAGE_FLOW.md)** - Detailed explanation of how agentic AI planning, execution, and reflection works
- **[Prompt Management](technical/PROMPT_MANAGEMENT.md)** - Prompt architecture, layered stack, validation, and security features
- **[API Key Implementation](technical/API_KEY_IMPLEMENTATION.md)** - Secure API key management, hashing, verification, and lifecycle
- **[Contract Test Protocol](technical/contract_test_protocol.md)** - Prompt validation contract, test protocol, and validation rules

## 📋 Quick Reference

### Setup
1. Follow [Kickstart Guide](guides/KICKSTART_GUIDE.md) for initial setup
2. Configure environment variables (see `.env.example`)
3. Run database migrations
4. Start the server

### Common Tasks
- **Setting up Telegram**: See [Telegram Setup](guides/TELEGRAM_SETUP.md)
- **Configuring MCP servers**: See [MCP Server Security](guides/MCP_SERVER_SECURITY.md)
- **Understanding architecture**: See [System Architecture](technical/SYSTEM_ARCHITECTURE.md)
- **Managing prompts**: See [Prompt Management](technical/PROMPT_MANAGEMENT.md)
- **API key management**: See [API Key Implementation](technical/API_KEY_IMPLEMENTATION.md)

### Testing
- See `tests/README.md` for test documentation
- Run tests: `pytest tests/ -v`

## 🔍 Finding What You Need

### I want to...
- **Get started quickly** → [Kickstart Guide](guides/KICKSTART_GUIDE.md)
- **Understand how the system works** → [System Architecture](technical/SYSTEM_ARCHITECTURE.md)
- **Set up a specific feature** → Check [User Guides](guides/)
- **Understand a technical concept** → Check [Technical Documentation](technical/)
- **Contribute to the project** → See [CONTRIBUTING.md](../CONTRIBUTING.md) in the root directory
- **Understand security** → See [MCP Server Security](guides/MCP_SERVER_SECURITY.md)

## 📝 Documentation Updates

Documentation is maintained alongside the codebase. If you find issues or have suggestions:
1. Open an issue on GitHub
2. Submit a pull request with documentation improvements
3. See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines
