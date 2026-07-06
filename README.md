# UNSW CLI

> ⚠️ **Disclaimer**: This is an **unofficial** open-source project created for **learning and reference purposes only**.
> It is not affiliated with, endorsed by, or officially connected to the University of New South Wales (UNSW) or any of its platforms.
> Use at your own risk. The authors assume **no responsibility** for any consequences arising from the use of this tool,
> including but not limited to account suspension, data loss, or violations of university IT policies.
> By using this software, you agree that you are solely responsible for your actions.

---

All-in-one UNSW toolkit — manage Moodle, WebCMS3, myUNSW, Handbook, Timetable and the Library from your terminal.

## Features

| Module | Description | Auth |
|--------|-------------|------|
| **Moodle** | Courses, assignments, grades | `MoodleSession` cookie |
| **WebCMS3** | CSE course content (lectures, labs, projects) | zID + zPass |
| **myUNSW** | Course enrolment, personal timetable, class search | Azure AD SSO session |
| **Handbook** | Course and program information | Public |
| **Timetable** | Public class schedule | Public |
| **Library** | Book search (opens Primo in browser) | Public |

## Installation

```bash
# Recommended: zero install with uv
git clone https://github.com/kurashizu/unsw-cli.git
cd unsw-cli
uv run unsw --help

# Or install with pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
# Log into a specific platform (uniform `--platform` syntax)
uv run unsw login --platform moodle  --browser        # Moodle via SSO
uv run unsw login --platform myunsw  --browser        # myUNSW via SSO
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword

# Interactive wizard — log into all platforms (skips already-authed)
uv run unsw login
uv run unsw login --platform all

# Check authentication status across all platforms
uv run unsw auth status

# Query course information (no auth required)
uv run unsw handbook course COMP2521
uv run unsw handbook search MATH
uv run unsw handbook area COMP
uv run unsw handbook program 3778

# View class timetable (no auth required)
uv run unsw timetable course COMP2521
uv run unsw timetable areas

# Personal timetable (myUNSW — requires login)
uv run unsw myunsw timetable

# Browse authenticated content
uv run unsw moodle courses
uv run unsw moodle assignments
uv run unsw moodle grades
uv run unsw webcms3 courses
uv run unsw webcms3 content COMP9444

# Course enrolment helpers (open myUNSW with instructions)
uv run unsw myunsw enrol COMP2521 1234
uv run unsw myunsw drop COMP2521

# Library search (opens Primo in browser)
uv run unsw library search "python programming"
uv run unsw library links

# Show current config
uv run unsw login --show
```

## Command Reference

### Top-level

| Command | Description | Auth Required |
|---------|-------------|---------------|
| `unsw login [--platform <name>]` | Log into one or all platforms | — |
| `unsw dashboard` | Unified dashboard overview | — |
| `unsw version` | Show version | — |

### `unsw auth`

| Command | Description |
|---------|-------------|
| `unsw auth status` | Authentication status for all platforms |
| `unsw auth guide` | Platform-specific authentication guides |
| `unsw auth login` | *(deprecated alias of `unsw login`)* |
| `unsw auth login-moodle` | *(deprecated; use `unsw login --platform moodle --browser`)* |

### `unsw handbook` (public, no auth)

| Command | Description |
|---------|-------------|
| `unsw handbook course <code>` | View course details |
| `unsw handbook search <query>` | Search courses |
| `unsw handbook area <code>` | List all courses in a subject area |
| `unsw handbook program <code>` | View program (degree) information |

### `unsw timetable` (public, no auth)

| Command | Description |
|---------|-------------|
| `unsw timetable course <code>` | Public class schedule for a course |
| `unsw timetable areas` | All subject areas |

### `unsw moodle` (cookie auth)

| Command | Description |
|---------|-------------|
| `unsw moodle courses` | List enrolled Moodle courses |
| `unsw moodle assignments` | View upcoming assignments |
| `unsw moodle grades` | View grades |

### `unsw webcms3` (zID + zPass auth)

| Command | Description |
|---------|-------------|
| `unsw webcms3 courses` | List enrolled WebCMS3 courses |
| `unsw webcms3 content <code>` | View course content |

### `unsw myunsw` (Azure AD SSO via browser)

| Command | Description |
|---------|-------------|
| `unsw myunsw login` | *(deprecated; use `unsw login --platform myunsw --browser`)* |
| `unsw myunsw courses` | List currently enrolled courses |
| `unsw myunsw timetable` | Personal class timetable |
| `unsw myunsw search <code>` | Search available classes |
| `unsw myunsw enrol <code> <class_nbr>` | Open myUNSW with enrol instructions |
| `unsw myunsw drop <code>` | Open myUNSW with drop instructions |
| `unsw myunsw open` | Open myUNSW in browser |

### `unsw library` (public)

| Command | Description |
|---------|-------------|
| `unsw library search <query>` | Search the catalog (opens browser) |
| `unsw library links` | Useful library links |

## Authentication

The CLI uses a uniform `--platform` flag for logging into any platform:

```bash
# Single platform
uv run unsw login --platform moodle  --browser
uv run unsw login --platform myunsw  --browser
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword

# All platforms (interactive wizard, skips already-authed)
uv run unsw login
uv run unsw login --platform all

# Show current config
uv run unsw login --show
```

### Moodle — Browser SSO (recommended)

```bash
uv run unsw login --platform moodle --browser
```

The CLI opens a headed Chromium window → you log in via Microsoft SSO → the `MoodleSession` cookie is captured automatically.

### Moodle — Manual cookie export

```bash
# 1. Log into https://moodle.telt.unsw.edu.au in your browser
# 2. Open DevTools (F12) → Application → Cookies → moodle.telt.unsw.edu.au
# 3. Copy the MoodleSession cookie value
# 4. Configure it:
uv run unsw login --platform moodle --set-cookie MoodleSession=<paste-value>
```

Moodle uses Azure AD SSO (Microsoft login) and does **not** support direct zID+zPass login. UNSW has not enabled the Moodle REST API, so the `MoodleSession` cookie is the only authentication mechanism.

### myUNSW — Browser SSO

```bash
uv run unsw login --platform myunsw --browser
```

Same flow as Moodle (Azure AD SSO). The session cookies are stored under the `myunsw_*` prefix in `cookies.json`.

### WebCMS3 — zID + zPass

```bash
uv run unsw login --platform webcms3 --zid z5123456 --zpass yourpassword
```

WebCMS3 supports direct zID + zPass login with a CSRF token. Credentials are stored in `~/.config/unsw-cli/config.yaml`.

### Check Status

```bash
uv run unsw auth status
```

Shows all platforms with real verification — whether each credential is valid, expired, or not configured.

### Backward Compatibility

The legacy commands still work and are marked `[DEPRECATED]` in their help text. Set `UNSW_CLI_SHOW_DEPRECATION=1` to see the deprecation hints at runtime:

| Old command | New command |
|---|---|
| `unsw login --browser` | `unsw login --platform moodle --browser` |
| `unsw login --zid X --zpass Y` | `unsw login --platform webcms3 --zid X --zpass Y` |
| `unsw login --set-cookie X=Y` | `unsw login --platform moodle --set-cookie X=Y` |
| `unsw auth login` | `unsw login` |
| `unsw auth login-moodle` | `unsw login --platform moodle --browser` |
| `unsw myunsw login` | `unsw login --platform myunsw --browser` |

## Output Formats

Most listing commands support `--json` for JSON output:

```bash
uv run unsw handbook course COMP2521 --json
uv run unsw timetable course COMP2521 --json
uv run unsw moodle courses --json
uv run unsw webcms3 courses --json
```

## Where Credentials Are Stored

| File | Contents |
|---|---|
| `~/.config/unsw-cli/config.yaml` | zID, zPass (plaintext by default), preferences |
| `~/.config/unsw-cli/cookies.json` | Session cookies (MoodleSession, myunsw_*, webcms3) |
| `~/.config/unsw-cli/data/` | Cached/scraped data directory |

The `save_cookies()` function merges with existing cookies so different platform cookies don't overwrite each other.

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

# All tests
uv run pytest tests/
```

The test suite includes:
- **Unit tests** — config persistence, output formatting, the cookie merge fix
- **Module tests** — mocked HTTP (`respx`) for all six platform modules
- **CLI smoke tests** — every command parses and runs (114 tests)
- **Integration tests** — real UNSW servers (Handbook, Timetable, Library)

## Project Structure

```
unsw-cli/
├── pyproject.toml
├── pytest.ini
├── README.md
├── .github/workflows/test.yml    # CI
├── unsw/
│   ├── cli.py                    # Main CLI entry point (all commands)
│   ├── config.py                 # Config + cookie persistence
│   ├── __init__.py
│   ├── auth/
│   │   ├── browser.py            # Playwright browser auto-login
│   │   ├── webcms3.py            # zID + zPass + CSRF login
│   │   ├── moodle.py             # MoodleSession cookie verification
│   │   └── myunsw.py             # myUNSW Azure AD SSO via browser
│   ├── modules/
│   │   ├── handbook.py           # Course + program scraping (SSR JSON)
│   │   ├── timetable.py          # Public timetable HTML parser
│   │   ├── moodle.py             # Moodle course/assignment/grade scraping
│   │   ├── webcms3.py            # WebCMS3 course/content scraping
│   │   ├── myunsw.py             # myUNSW enrolled courses, timetable
│   │   └── library.py            # Primo search URL generation
│   └── utils/
│       ├── http.py               # Shared HTTP client
│       └── output.py             # Rich tables, JSON formatting
└── tests/
    ├── conftest.py               # Fixtures (isolated_config, cli_runner)
    ├── test_config.py            # Config + cookie merge tests
    ├── test_output.py            # Output utility tests
    ├── test_cli.py               # CLI smoke + --platform tests
    ├── test_integration.py       # Real UNSW endpoint tests
    ├── auth/                     # Auth module tests (mocked HTTP)
    └── modules/                  # Module tests (mocked HTTP)
```

## Why Not Just Use the Browser?

- Faster than opening a browser for routine checks
- Scriptable — pipe into other tools, cron jobs, status bars
- Searchable history — keep notes on assignments and grades
- Keyboard-first workflow

## Known Limitations

- **Moodle assignments/grades scraping** — relies on theme selectors; may need updates if UNSW Moodle UI changes
- **myUNSW enrolment** — uses PeopleSoft forms which require complex JavaScript; we open the browser with step-by-step instructions rather than automating the form
- **CourseLoop API** (Handbook data source) — CloudFront-protected, can't reverse-engineer
- **Primo library catalog** — Angular SPA, no public REST API; we generate search URLs

## License

MIT