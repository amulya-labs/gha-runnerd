# Contributing to gha-runnerd

Thank you for your interest in contributing to gha-runnerd! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to a Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce** the problem
- **Expected behavior** vs actual behavior
- **Environment details** (OS, Python version, Docker version)
- **Log output** if relevant (from `journalctl` or deployment script)

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- **Clear use case** - why is this enhancement needed?
- **Proposed solution** - how should it work?
- **Alternatives considered** - what other approaches did you think about?

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Make your changes** following the coding standards below
3. **Test your changes** thoroughly
4. **Update documentation** if you're changing functionality
5. **Submit a pull request** with a clear description

## Development Setup

```bash
# Clone your fork
git clone https://github.com/your-username/gha-runnerd.git
cd gha-runnerd

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pylint black isort
```

## Coding Standards

- **Python style**: Follow PEP 8 guidelines
- **Formatting**: Use `black` for code formatting
- **Imports**: Use `isort` for import sorting
- **Type hints**: Add type hints for function parameters and return values
- **Docstrings**: Add docstrings for classes and functions
- **Error handling**: Provide clear error messages with actionable advice

### Running Linters

```bash
# Check syntax
python -m py_compile deploy-host.py

# Format code
black deploy-host.py

# Sort imports
isort deploy-host.py

# Run linter
pylint deploy-host.py
```

## Testing

Before submitting a PR, test your changes:

1. **Syntax check**: Ensure Python syntax is valid
2. **Dry run**: Test with a test organization/config if possible
3. **Documentation**: Verify README examples still work
4. **Edge cases**: Consider error conditions and edge cases

### Manual Testing

```bash
# Test configuration parsing
python -c "from deploy_host import HostDeployer; d = HostDeployer('config.example.yml')"

# Test with dry-run (if implemented)
sudo -E ./deploy-host.py --dry-run
```

## Documentation

- **README.md**: Update if adding features or changing behavior
- **config.example.yml**: Update if adding new configuration options
- **Inline comments**: Add comments for complex logic
- **Docstrings**: Document function parameters and return values

## Commit Messages

Write clear, concise commit messages:

```
Add support for ARM64 runners

- Add architecture detection
- Update runner binary download logic
- Add ARM64 to config examples
```

- Use present tense ("Add feature" not "Added feature")
- Keep first line under 72 characters
- Provide details in subsequent lines if needed

## Release Process

Maintainers will handle releases:

1. Version bump in relevant files
2. Update CHANGELOG (if we add one)
3. Create GitHub release with notes
4. Tag the release

## Questions?

Feel free to open an issue for questions or join discussions in existing issues.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
