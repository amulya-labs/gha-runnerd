# Tests

This directory contains integration tests for gha-runnerd.

## Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_integration.py

# Run with verbose output
python -m pytest tests/ -v

# Run tests using unittest (no pytest needed)
python tests/test_integration.py
```

## Test Coverage

### `test_integration.py`

Integration tests covering:

- **Configuration Parsing**
  - Valid minimal config loading
  - Invalid config rejection
  - GPU runner configuration
  - Multiple runner configurations
  
- **Runner Name Parsing**
  - CPU generic runner parsing
  - CPU specialized runner parsing (e.g., docker)
  - GPU runner parsing
  - Label generation for different runner types
  - Service name generation
  - Registered name generation

- **Runner Validation**
  - Valid runner config validation
  - Invalid runner size rejection

- **Config Defaults**
  - Default runner_user and runner_uid application

## Adding New Tests

1. Create new test files in this directory following the naming pattern `test_*.py`
2. Use the unittest framework (built-in) or pytest
3. Import necessary classes from `deploy-host.py`
4. Add test documentation describing what's being tested

## CI Integration

Tests are automatically run in CI via the `.github/workflows/ci.yml` workflow.
