# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Complete documentation overhaul for public launch
- "What is this?" section with value propositions for both technical and non-technical readers
- Visual architecture diagram showing how runners, containers, and caching work together
- Streamlined comparison table focusing on key differentiators
- Examples for Python, Node.js, Rust, and Docker workflows
- Configuration examples (minimal, production, GPU-enabled)
- Development dependencies in requirements-dev.txt
- Comprehensive migration guide for Docker-based runners, GitHub-hosted runners, and ARC
- Security policy and best practices documentation
- Code of Conduct (Contributor Covenant 2.1)
- Contributing guidelines
- Integration tests for configuration parsing and validation
- CI/CD workflows for linting and testing

### Changed
- README title changed to "gha-runnerd" with clearer tagline
- Improved README structure with "Quick Start" prominently featured
- Consolidated "Why gha-runnerd?" section with cleaner comparison table
- Enhanced CLI with --list, --remove, --upgrade, and --config options
- Better error messages and validation
- Consolidated Prerequisites and Setup sections in documentation

### Fixed
- Documentation inconsistencies and duplications
- Example file references in CONTRIBUTING.md

## [1.0.0] - 2026-02-10

### Added
- Initial public release
- Host-based GitHub Actions runner deployment tool
- Support for CPU and GPU runners
- Automatic runner registration via GitHub CLI
- Systemd service management
- Resource limits via systemd (CPU, memory, PIDs)
- Shared cache directory support for gha-opencache and other cache actions
- Workspace cleanup hooks for Docker container permissions
- Flexible runner naming with type, size, and optional category
- Configuration validation and dry-run mode
- Comprehensive troubleshooting guide

### Features
- Container-first workflow support (no nested container issues)
- Lightning-fast local caching with sub-second restore times
- Full `jobs.container` support
- Service container support
- Configurable runner sizes (xs, small, medium, large, max)
- Optional specialized runners (docker, bazel, etc.)
- Automatic label generation from runner names
- GitHub API integration for label enforcement

[Unreleased]: https://github.com/amulya-labs/gha-runnerd/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/amulya-labs/gha-runnerd/releases/tag/v1.0.0
