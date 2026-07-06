# UNSW CLI

> ⚠️ **Disclaimer**: This is an **unofficial** open-source project created for **learning and reference purposes only**.
> It is not affiliated with, endorsed by, or officially connected to the University of New South Wales (UNSW) or any of its platforms.
> Use at your own risk. The authors assume **no responsibility** for any consequences arising from the use of this tool,
> including but not limited to account suspension, data loss, or violations of university IT policies.
> By using this software, you agree that you are solely responsible for your actions.

---

All-in-one UNSW toolkit — manage Moodle, WebCMS3, Handbook, Timetable and the Library from your terminal.

## Installation

```bash
# Recommended: use uv (zero install)
cd unsw-cli
uv run unsw --help

# Or install with pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
# View help
uv run unsw --help

# Log into a specific platform (uniform `--platform` syntax):
uv run unsw login --platform moodle --browser      # Moodle via SSO
uv run unsw login --platform myunsw --browser      # myUNSW via SSO
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword

# Interactive wizard — log into all platforms (skips already-authed):
uv run unsw login

# Check authentication status for all platforms
uv run unsw auth status

# Query course information (no auth required)
uv run unsw handbook course COMP2521
uv run unsw handbook search MATH
uv run unsw handbook area COMP

# View class timetable (no auth required)
uv run unsw timetable course COMP2521

# Requires authentication
uv run unsw moodle courses
uv run unsw webcms3 courses
```

## Command Reference

| Command | Description | Auth Required |
|---------|-------------|---------------|
| `unsw login` | Configure authentication (interactive wizard) | — |
| `unsw auth status` | Authentication status for all platforms | — |
| `unsw auth guide` | Platform-specific auth instructions | — |
| `unsw dashboard` | Unified dashboard overview | — |
| `unsw handbook course <code>` | View course details | ❌ |
| `unsw handbook search <query>` | Search courses | ❌ |
| `unsw handbook area <code>` | All courses in a subject area | ❌ |
| `unsw timetable course <code>` | View class schedule | ❌ |
| `unsw timetable areas` | Subject areas listing | ❌ |
| `unsw moodle courses` | List Moodle courses | ✅ Cookie |
| `unsw moodle assignments` | View assignments | ✅ Cookie |
| `unsw moodle grades` | View grades | ✅ Cookie |
| `unsw webcms3 courses` | List WebCMS3 courses | ✅ zID+zPass |
| `unsw webcms3 content <code>` | View course content | ✅ zID+zPass |
| `unsw library search <query>` | Search the library | ❌ |
| `unsw library links` | Useful library links | ❌ |

## Authentication

The CLI uses a uniform `--platform` flag for logging into any platform:

```bash
# Log into a single platform
uv run unsw login --platform moodle  --browser
uv run unsw login --platform myunsw  --browser
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword

# Log into all platforms (interactive wizard, skips already-authed):
uv run unsw login
uv run unsw login --platform all
```

### Moodle (Browser auto-login — recommended)

```bash
uv run unsw login --platform moodle --browser
```

Moodle uses Azure AD SSO (Microsoft login) and does **not** support direct zID+zPass login. UNSW has not enabled the Moodle REST API, so the only way to authenticate is via the `MoodleSession` cookie.

### Moodle (Manual cookie)

```bash
# 1. Log into https://moodle.telt.unsw.edu.au in your browser
# 2. Open DevTools (F12) → Application → Cookies → moodle.telt.unsw.edu.au
# 3. Copy the MoodleSession cookie value
# 4. Set it with:
uv run unsw login --platform moodle --set-cookie MoodleSession=<paste-value>
```

### WebCMS3

```bash
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword
```

### Backward compatibility

The legacy commands still work but print a deprecation hint:

| Old command | New command |
|---|---|
| `unsw login --browser` | `unsw login --platform moodle --browser` |
| `unsw login --zid X --zpass Y` | `unsw login --platform webcms3 --zid X --zpass Y` |
| `unsw login --set-cookie X=Y` | `unsw login --platform moodle --set-cookie X=Y` |
| `unsw auth login` | `unsw login` |
| `unsw auth login-moodle` | `unsw login --platform moodle --browser` |
| `unsw myunsw login` | `unsw login --platform myunsw --browser` |

Set `UNSW_CLI_SHOW_DEPRECATION=1` to see the deprecation hints.

### Check Authentication Status

```bash
uv run unsw auth status
```

Shows all platform statuses with real verification. Displays whether each credential is valid, expired, or not configured.

## Output Formats

All commands support `--json` for JSON output:

```bash
uv run unsw handbook course COMP2521 --json
uv run unsw timetable course COMP2521 --json
```

## Project Structure

```
unsw-cli/
├── pyproject.toml
├── unsw/
│   ├── cli.py              # Main CLI entry point
│   ├── config.py           # Configuration management (YAML)
│   ├── __init__.py
│   ├── auth/
│   │   ├── browser.py      # Browser auto-login (Playwright)
│   │   ├── webcms3.py      # WebCMS3 zID+zPass auth
│   │   └── moodle.py       # Moodle cookie verification
│   ├── modules/
│   │   ├── handbook.py     # UNSW Handbook scraper
│   │   ├── timetable.py    # Timetable parser
│   │   ├── moodle.py       # Moodle course/assignment/grade scraper
│   │   ├── webcms3.py      # WebCMS3 course/content scraper
│   │   └── library.py      # Library search URL generator
│   └── utils/
│       ├── http.py          # Shared HTTP client
│       └── output.py        # Output formatting (Rich tables, JSON)
```

## Testing

```bash
# Install dev dependencies
uv sync --all-extras

# Run unit + module tests (no network required)
uv run pytest tests/ --ignore=tests/test_integration.py

# Run integration tests against real UNSW endpoints
uv run pytest tests/test_integration.py -m network

# Run integration tests that need stored credentials
uv run pytest tests/test_integration.py -m auth
```

The test suite includes:
- **Unit tests** for config persistence, output formatting, and the cookie merge fix
- **Module tests** using mocked HTTP (`respx`) for all five platform modules
- **CLI smoke tests** verifying every command parses and runs
- **Integration tests** against real UNSW servers (Handbook, Timetable, Library)

## License

MIT
