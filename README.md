# SOCA Project

A modern C++ project built with Bazel, featuring automated code quality checks and comprehensive testing.

## 🚀 Quick Start

### Prerequisites

- [Bazel](https://bazel.build/) (latest version)
- C++ compiler (GCC/Clang)
- Git

### Building the Project

```bash
# Clone the repository
git clone <repository-url>
cd soca

# Build all targets
bazel build //...

# Run tests
bazel test //...

# Run specific test
bazel run //bazel_workspace:hello_world_test
```

## 📁 Project Structure

```
soca/
├── bazel_workspace/          # Main C++ package
│   ├── BUILD                # Bazel build rules
│   ├── hello_world.h        # HelloWorld class header
│   ├── hello_world.cpp      # HelloWorld class implementation
│   └── test.cpp            # Unit tests
├── .gitignore              # Git ignore rules
├── .pre-commit-config.yaml # Pre-commit hooks configuration
├── WORKSPACE               # Bazel workspace configuration
└── README.md              # This file
```

## 🛠️ Development

### Code Quality

This project uses pre-commit hooks to maintain code quality:

```bash
# Install pre-commit hooks (already done)
pre-commit install

# Run hooks manually on all files
pre-commit run --all-files

# Run specific hook
pre-commit run clang-format --all-files
```

### Available Pre-commit Hooks

- **General**: Trailing whitespace, end-of-file fixes, merge conflict detection
- **C++**: clang-format (Google style), clang-tidy
- **Bazel**: buildifier (BUILD file formatting and linting)
- **Python**: black, isort, flake8 (for any Python scripts)
- **Git**: Conventional commit message validation

### Adding New Code

1. Create your C++ files in appropriate directories
2. Add BUILD rules for new libraries/binaries/tests
3. Run pre-commit hooks: `pre-commit run --all-files`
4. Build and test: `bazel build //... && bazel test //...`
5. Commit your changes

## 🧪 Testing

```bash
# Run all tests
bazel test //...

# Run tests with verbose output
bazel test //... --test_output=errors

# Run specific test
bazel test //bazel_workspace:hello_world_test
```

## 📋 Bazel Commands

```bash
# Build everything
bazel build //...

# Clean build artifacts
bazel clean

# Build specific target
bazel build //bazel_workspace:hello_world

# Run specific binary
bazel run //bazel_workspace:hello_world_test

# Query available targets
bazel query //...
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run pre-commit hooks: `pre-commit run --all-files`
5. Build and test: `bazel build //... && bazel test //...`
6. Commit your changes with conventional commit messages
7. Push to your fork
8. Create a Pull Request

### Commit Message Format

This project follows [Conventional Commits](https://conventionalcommits.org/):

```
type(scope): description

Types: feat, fix, docs, style, refactor, test, chore
```

Examples:
- `feat: add new HelloWorld class`
- `fix: correct memory leak in test`
- `docs: update README with build instructions`

## 📄 License

[Add your license here - e.g., MIT, Apache 2.0, etc.]

## 📞 Support

If you have any questions or issues, please open an issue on GitHub.
