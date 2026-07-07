"""UNSW CLI - Main entry point.

Usage:
    unsw --help
    unsw login
    unsw handbook search <query>
    unsw handbook course <code>
    unsw timetable course <code>
    unsw moodle courses
    unsw moodle assignments
    unsw webcms3 courses
    unsw library search <query>
    unsw dashboard
"""

from __future__ import annotations

from typing import Optional

import typer

from unsw import __version__
from unsw.config import CONFIG_DIR, CONFIG_FILE, Config
from unsw.utils.output import (
    console,
    format_output,
    print_error,
    print_info,
    print_panel,
    print_success,
    print_warning,
)

# Typer app
app = typer.Typer(
    name="unsw",
    help="UNSW CLI - Manage Moodle, WebCMS3, Handbook, Timetable & Library from your terminal",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Sub-apps
auth_app = typer.Typer(help="🔐 Unified authentication management")
handbook_app = typer.Typer(help="📖 UNSW Handbook - course and program information")
timetable_app = typer.Typer(help="📅 UNSW Timetable - class schedule lookup")
moodle_app = typer.Typer(help="🎓 Moodle - courses, assignments and grades")
webcms3_app = typer.Typer(help="💻 WebCMS3 - CSE course content")
library_app = typer.Typer(help="📚 Library - book search")
myunsw_app = typer.Typer(help="🎓 myUNSW - course enrolment and student services")

app.add_typer(auth_app, name="auth")
app.add_typer(handbook_app, name="handbook")
app.add_typer(timetable_app, name="timetable")
app.add_typer(moodle_app, name="moodle")
app.add_typer(webcms3_app, name="webcms3")
app.add_typer(library_app, name="library")
app.add_typer(myunsw_app, name="myunsw")

# ──────────────────────────────────────────────
# Global commands
# ──────────────────────────────────────────────


@app.command()
def login(
    platform: Optional[str] = typer.Option(
        None,
        "--platform",
        "-p",
        help="Target platform: 'moodle', 'webcms3', 'myunsw' or 'all' (default)",
        case_sensitive=False,
    ),
    zid: Optional[str] = typer.Option(None, "--zid", help="Your zID (e.g. z5123456)"),
    zpass: Optional[str] = typer.Option(
        None, "--zpass", help="Your zPass", hide_input=True
    ),
    set_cookie: Optional[str] = typer.Option(
        None, "--set-cookie", help="Set a MoodleSession cookie (Name=Value)"
    ),
    browser: bool = typer.Option(
        False,
        "--browser",
        help="Open browser for SSO login (auto-capture cookie)",
    ),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """🔐 Log into one or all UNSW platforms.

    Without --platform, runs the interactive wizard for all platforms.
    Use --platform to target a specific one.

    Platform-specific notes:
    - moodle / myunsw: require Azure AD SSO — use --browser
    - webcms3: requires zID + zPass — use --zid and --zpass

    Examples:

    # Interactive wizard (recommended):
    unsw login

    # Log into one platform:
    unsw login --platform moodle --browser
    unsw login --platform myunsw --browser
    unsw login --platform webcms3 --zid z5530104 --zpass secret

    # Log into all authed platforms (skips already-authed ones):
    unsw login --platform all

    # Manually set a MoodleSession cookie:
    unsw login --platform moodle --set-cookie MoodleSession=abc123

    # Show current config:
    unsw login --show
    """
    config = Config()

    # Normalize --platform value
    if platform is not None:
        platform = platform.lower().strip()
    valid_platforms = {"moodle", "webcms3", "myunsw", "all"}
    if platform is not None and platform not in valid_platforms:
        print_error(
            f"Invalid --platform '{platform}'. "
            f"Must be one of: {', '.join(sorted(valid_platforms))}"
        )
        raise typer.Exit(code=1)

    # If no --platform specified but other flags given, infer the platform.
    # This preserves backward compatibility: `unsw login --browser` → moodle,
    # `unsw login --zid ... --zpass ...` → webcms3.
    if platform is None:
        if zid or zpass:
            platform = "webcms3"
        elif browser or set_cookie:
            platform = "moodle"
        else:
            platform = "all"  # Interactive wizard

    # ── Single-platform flows (non-interactive) ──────────────

    if platform == "moodle":
        if browser:
            from unsw.auth.sso import sso_login_all

            results = sso_login_all(config, platforms=["moodle"])
            if results.get("moodle"):
                print_success("Moodle login configured!")
            return
        if set_cookie:
            if "=" in set_cookie:
                key, value = set_cookie.split("=", 1)
                cookies = config.load_cookies()
                cookies[key] = value
                config.save_cookies(cookies)
                print_success(f"Cookie '{key}' saved")
                return
            print_error("Invalid cookie format. Use: Name=Value")
            raise typer.Exit(code=1)
        # No browser and no cookie flag → fall through to interactive wizard
        # for Moodle only
        print_info("Use --browser to open the Moodle SSO login, or")
        print_info("use --set-cookie MoodleSession=<value> to set manually.")
        return

    if platform == "myunsw":
        if browser:
            from unsw.auth.sso import sso_login_all

            results = sso_login_all(config, platforms=["myunsw"])
            if results.get("myunsw"):
                print_success("myUNSW login configured!")
            return
        print_info("myUNSW requires browser login. Use --browser.")
        return

    if platform == "webcms3":
        if zid:
            config.auth.zid = zid
        if zpass:
            config.auth.zpass = zpass
        if zid or zpass:
            config.save()
            from unsw.auth.webcms3 import verify_credentials

            print_success("WebCMS3 credentials saved.")
            if config.auth.zid and config.auth.zpass:
                print_info("Verifying WebCMS3...")
                ok = verify_credentials(config.auth.zid, config.auth.zpass)
                if ok:
                    print_success("WebCMS3 login verified!")
                else:
                    print_warning("WebCMS3 login failed. Check your zID and zPass.")
            return
        if show:
            _show_config(config)
            return
        # No flags → prompt for zID/zPass interactively
        _do_login(zid, zpass, set_cookie, show)
        return

    # platform == "all" (or unspecified with no inferred flags)
    if show:
        _show_config(config)
        return
    _do_login(zid, zpass, set_cookie, show)


@app.command()
def dashboard():
    """📊 Show a unified dashboard overview."""
    config = Config()
    lines = []

    lines.append(f"# UNSW CLI Dashboard v{__version__}")
    lines.append("")
    lines.append(f"**zID**: {config.auth.zid or 'Not configured'}  ")
    lines.append("  ")
    # Check Moodle cookie status
    saved_cookies = config.load_cookies()
    has_moodle = bool(
        saved_cookies.get("MoodleSession") or config.auth.moodle_session_cookie
    )
    lines.append(
        f"**Moodle**: {'✅ Cookie configured' if has_moodle else '⚠️  Not configured'}  "
    )
    lines.append("  ")
    lines.append(
        f"**WebCMS3**: {'✅ zID/zPass configured' if config.auth.zid and config.auth.zpass else '⚠️  Not configured'}  "
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Quick Commands")
    lines.append("")
    lines.append("- `unsw handbook course COMP2521` — View course info")
    lines.append("- `unsw handbook search COMP` — Search courses")
    lines.append("- `unsw timetable course COMP2521` — View timetable")
    lines.append("- `unsw moodle courses` — List Moodle courses (needs auth)")
    lines.append("- `unsw webcms3 courses` — List WebCMS3 courses (needs auth)")
    lines.append("- `unsw library search python` — Search library")

    print_panel("UNSW CLI Dashboard", "\n".join(lines))

    if config.auth.zid and config.auth.zpass:
        print_info("Tip: Run `unsw login --show` to view your configuration.")


@app.command()
def version():
    """Show version information."""
    print_info(f"UNSW CLI v{__version__}")


# ──────────────────────────────────────────────
# Auth commands
# ──────────────────────────────────────────────


@auth_app.command()
def status():
    """📊 Show authentication status for all platforms."""
    config = Config()
    rows = []

    with console.status("Checking authentication status..."):
        # ── 1. WebCMS3 ──
        if not config.auth.zid:
            rows.append(["WebCMS3", "zID", "⚪ Not configured", "Run: unsw login"])
        elif not config.auth.zpass:
            rows.append(["WebCMS3", "zPass", "⚪ Not configured", "Run: unsw login"])
        else:
            from unsw.auth.webcms3 import verify_credentials

            ok = verify_credentials(config.auth.zid, config.auth.zpass)
            if ok:
                rows.append(["WebCMS3", f"{config.auth.zid}", "✅ Verified", ""])
            else:
                rows.append(
                    [
                        "WebCMS3",
                        f"{config.auth.zid}",
                        "❌ Login failed",
                        "Check zID/zPass",
                    ]
                )

        # ── 2. Moodle Cookie ──
        saved = config.load_cookies()
        cookie_val = saved.get("MoodleSession") or config.auth.moodle_session_cookie
        if cookie_val:
            from unsw.auth.moodle import verify_cookie

            ok = verify_cookie(cookie_val)
            if ok:
                rows.append(["Moodle (Cookie)", "MoodleSession", "✅ Valid", ""])
            else:
                rows.append(
                    [
                        "Moodle (Cookie)",
                        "MoodleSession",
                        "❌ Expired",
                        "unsw login --browser",
                    ]
                )
        else:
            rows.append(
                ["Moodle (Cookie)", "—", "⚪ Not configured", "unsw login --browser"]
            )

        # ── 3. myUNSW ──
        saved = config.load_cookies()
        myunsw_cookies = {k: v for k, v in saved.items() if k.startswith("myunsw_")}
        if myunsw_cookies:
            from unsw.auth.myunsw import verify_session

            ok = verify_session(config)
            if ok:
                rows.append(["myUNSW", "Session", "✅ Valid", ""])
            else:
                rows.append(["myUNSW", "Session", "❌ Expired", "unsw myunsw login"])
        else:
            rows.append(["myUNSW", "—", "⚪ Not configured", "unsw myunsw login"])

        # ── 4. Handbook / Timetable / Library ──
        rows.append(["Handbook", "—", "✅ Public", "No auth needed"])
        rows.append(["Timetable", "—", "✅ Public", "No auth needed"])
        rows.append(["Library", "—", "✅ Public", "No auth needed"])

    format_output(
        [dict(zip(["Platform", "Account", "Status", "Action"], r)) for r in rows],
        columns=["Platform", "Account", "Status", "Action"],
        title="🔐 Authentication Status",
        output_format="table",
    )


@auth_app.command(name="login")
def auth_login(
    zid: Optional[str] = typer.Option(None, "--zid", help="Your zID (e.g. z5123456)"),
    zpass: Optional[str] = typer.Option(
        None, "--zpass", help="Your zPass", hide_input=True
    ),
    set_cookie: Optional[str] = typer.Option(
        None, "--set-cookie", help="Set a cookie (e.g. MoodleSession=abc123)"
    ),
    browser: bool = typer.Option(
        False,
        "--browser",
        help="Open browser to log into Moodle via SSO (auto-capture cookie)",
    ),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """ Configure authentication for UNSW platforms.

    [DEPRECATED] Prefer `unsw login` (works the same way).
    Use `unsw login --platform <name>` to target a specific platform.
    """
    _deprecation_hint("unsw auth login", "unsw login")
    if browser:
        from unsw.auth.browser import moodle_login_via_browser

        config = Config()
        success = moodle_login_via_browser(config)
        if success:
            print_success("Moodle login configured!")
        return
    _do_login(zid, zpass, set_cookie, show)


@auth_app.command()
def login_moodle():
    """🌐 Open browser to log into Moodle and auto-capture cookie.

    [DEPRECATED] Prefer `unsw login --platform moodle --browser`.
    """
    _deprecation_hint(
        "unsw auth login-moodle", "unsw login --platform moodle --browser"
    )
    from unsw.auth.browser import moodle_login_via_browser

    config = Config()
    print_info("Moodle Browser Login")
    print_info("=" * 40)
    print_info("A browser window will open for you to log into Moodle.")
    print_info("The session cookie will be captured automatically.\n")

    success = moodle_login_via_browser(config)
    if success:
        print_success("Moodle login configured! You can now use:")
        print_info("  unsw moodle courses")
        print_info("  unsw auth status")
    else:
        print_error("Failed to capture Moodle cookie.")


@auth_app.command()
def guide():
    """📖 Show platform-specific authentication guides."""
    lines = [
        "### 🔑 Platform Authentication Guide",
        "",
        "---",
        "### WebCMS3 (webcms3.cse.unsw.edu.au)",
        "",
        "WebCMS3 supports direct zID + zPass login.",
        "",
        "  ```",
        "  unsw login --zid z5123456 --zpass yourpassword",
        "  ```",
        "",
        "---",
        "### Moodle (moodle.telt.unsw.edu.au)",
        "",
        "Moodle uses Microsoft Azure AD SSO, so we can't login directly with zID+zPass.",
        "",
        "#### Option 1: Browser auto-login (recommended)",
        "",
        "The CLI opens a browser window — you log in, and the cookie is captured automatically:",
        "",
        "  ```",
        "  unsw login --browser",
        "  # or",
        "  unsw auth login-moodle",
        "  ```",
        "",
        "> Single command: browser opens → you log in → cookie captured → ready to use",
        "",
        "#### Option 2: Manual cookie export",
        "",
        "1. Open https://moodle.telt.unsw.edu.au in a browser and log in",
        "2. Open developer tools:",
        "   - **Chrome/Edge**: F12 → Application → Cookies → moodle.telt.unsw.edu.au",
        "   - **Firefox**: F12 → Storage → Cookies",
        "   - **Safari**: Develop → Show Web Inspector → Storage → Cookies",
        "3. Find the `MoodleSession` cookie and copy its Value",
        "4. Configure the CLI:",
        "   ```",
        "   unsw login --set-cookie MoodleSession=<paste-value>",
        "   ```",
        "",
        "> ⚠️ The cookie expires after you sign out or after some time — re-export if needed",
        "> 💡 Export the cookie right after logging in — do NOT click Log out",
        "",
        "Verify: ```unsw auth status``` — check Moodle (Cookie) shows ✅ Valid",
        "",
        "---",
        "### myUNSW (my.unsw.edu.au)",
        "",
        "myUNSW uses the same Azure AD SSO as Moodle. Browser login required.",
        "",
        "  ```",
        "  unsw myunsw login",
        "  ```",
        "",
        "Browser opens → log in via Azure AD → session captured automatically.",
        "",
        "---",
        "### Public Platforms (No Auth Needed)",
        "",
        "- **Handbook** (handbook.unsw.edu.au) — Public",
        "- **Timetable** (timetable.unsw.edu.au) — Public",
        "- **Library** (primoa.library.unsw.edu.au) — Public search",
    ]
    print_panel("📖 Authentication Guide", "\n".join(lines))


# ──────────────────────────────────────────────
# Handbook commands
# ──────────────────────────────────────────────


@handbook_app.command()
def search(
    query: str,
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
    max_results: int = typer.Option(10, "--max", "-m", help="Maximum results"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """🔍 Search courses in the UNSW Handbook."""
    from unsw.modules.handbook import HandbookModule

    module = HandbookModule()
    with console.status(f"Searching for '{query}'..."):
        results = module.search(query, year, max_results)

    if not results:
        print_info(f"No courses found matching '{query}'")
        return

    fmt = "json" if json_output else "table"
    format_output(
        results,
        columns=["code", "title", "credit_points", "level", "school"],
        title=f"Course Search: {query} (Year {year})",
        output_format=fmt,
    )


@handbook_app.command()
def course(
    code: str,
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """📖 View detailed course information."""
    from unsw.modules.handbook import HandbookModule

    module = HandbookModule()
    with console.status(f"Fetching {code}..."):
        result = module.get_course(code, year)

    if not result:
        print_error(f"Course '{code}' not found for {year}")
        return

    if json_output:
        format_output(result, output_format="json")
        return

    # Pretty display
    lines = [
        f"**{result['code']}** — {result['title']}",
        "",
        f"- **Credit Points**: {result['credit_points']}",
        f"- **Level**: {result['level']}",
        f"- **School**: {result['school']}",
        f"- **Faculty**: {result['faculty']}",
        f"- **Status**: {result['status']}",
        f"- **Pre-requisites**: {result['pre_requisites'] or 'None'}",
        f"- **URL**: {result['url']}",
    ]
    print_panel(f"📖 {code}", "\n".join(lines))


@handbook_app.command()
def program(
    code: str,
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
):
    """📋 View program (degree) information."""
    from unsw.modules.handbook import HandbookModule

    module = HandbookModule()
    with console.status(f"Fetching program {code}..."):
        result = module.get_program(code, year)

    if not result:
        print_error(f"Program '{code}' not found for {year}")
        return

    format_output(result, title=f"Program: {code}")


@handbook_app.command()
def area(
    code: str,
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
):
    """📂 List all courses in a subject area (e.g. COMP)."""
    from unsw.modules.handbook import HandbookModule

    module = HandbookModule()
    with console.status(f"Fetching courses in {code.upper()}..."):
        codes = module.search_by_area(code, year)

    if not codes:
        print_info(f"No courses found for area '{code.upper()}'")
        return

    format_output(
        [{"code": c} for c in codes],
        columns=["code"],
        title=f"Courses in {code.upper()} ({len(codes)} total)",
    )


# ──────────────────────────────────────────────
# Timetable commands
# ──────────────────────────────────────────────


@timetable_app.command()
def course(
    code: str,
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """📅 View class timetable for a course."""
    from unsw.modules.timetable import TimetableModule

    module = TimetableModule()
    with console.status(f"Fetching timetable for {code}..."):
        classes = module.get_course_classes(code, year)

    if not classes:
        print_info(f"No class data found for {code} in {year}")
        return

    fmt = "json" if json_output else "table"
    format_output(
        classes,
        columns=["period", "activity", "section", "class", "status", "enrols"],
        title=f"Timetable: {code.upper()} ({year})",
        output_format=fmt,
    )


@timetable_app.command()
def areas(
    year: int = typer.Option(2026, "--year", "-y", help="Academic year"),
):
    """🗂️ List all subject areas."""
    from unsw.modules.timetable import TimetableModule

    module = TimetableModule()
    with console.status("Fetching subject areas..."):
        areas = module.search_by_year(year)

    if not areas:
        print_info(f"No subject areas found for {year}")
        return

    format_output(
        areas,
        columns=["code", "campus"],
        title=f"Subject Areas ({year})",
    )


# ──────────────────────────────────────────────
# Moodle commands
# ──────────────────────────────────────────────


@moodle_app.command()
def courses(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """🎓 List your Moodle courses."""
    from unsw.modules.moodle import MoodleModule

    config = Config()
    module = MoodleModule(config)
    with console.status("Fetching Moodle courses..."):
        result = module.get_courses()

    if not result:
        print_error(
            "Could not fetch courses. Check your Moodle configuration (run `unsw login`)."
        )
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["id", "shortname", "fullname"],
        title="Moodle Courses",
        output_format=fmt,
    )


@moodle_app.command()
def assignments(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """📝 List upcoming assignments."""
    from unsw.modules.moodle import MoodleModule

    config = Config()
    module = MoodleModule(config)
    with console.status("Fetching assignments..."):
        result = module.get_assignments()

    if not result:
        print_info("No assignments found or Moodle not configured.")
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["course", "name", "due"],
        title="Upcoming Assignments",
        output_format=fmt,
    )


@moodle_app.command()
def grades(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """📊 View your grades."""
    from unsw.modules.moodle import MoodleModule

    config = Config()
    module = MoodleModule(config)
    with console.status("Fetching grades..."):
        result = module.get_grades()

    if not result:
        print_info("No grades found or Moodle not configured.")
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["course", "grade", "max"],
        title="Course Grades",
        output_format=fmt,
    )


# ──────────────────────────────────────────────
# WebCMS3 commands
# ──────────────────────────────────────────────


@webcms3_app.command()
def courses(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """💻 List your WebCMS3 courses."""
    from unsw.modules.webcms3 import WebCMS3Module

    config = Config()
    if not config.auth.zid or not config.auth.zpass:
        print_error("Please configure your zID and zPass first: unsw login")
        return

    module = WebCMS3Module(config)
    with console.status("Fetching WebCMS3 courses..."):
        result = module.get_courses()

    if not result:
        print_error("Could not fetch WebCMS3 courses. Check your credentials.")
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["code", "name"],
        title="WebCMS3 Courses",
        output_format=fmt,
    )


@webcms3_app.command()
def content(code: str):
    """📄 View content for a WebCMS3 course."""
    from unsw.modules.webcms3 import WebCMS3Module

    config = Config()
    if not config.auth.zid or not config.auth.zpass:
        print_error("Please configure your zID and zPass first: unsw login")
        return

    module = WebCMS3Module(config)
    with console.status(f"Fetching content for {code}..."):
        result = module.get_course_content(code)

    if not result:
        print_info(f"No content found for {code}")
        return

    format_output(
        result,
        columns=["title"],
        title=f"WebCMS3 Content: {code.upper()}",
    )


# ──────────────────────────────────────────────
# Library commands
# ──────────────────────────────────────────────


@library_app.command()
def search(
    query: str,
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open in browser"),
):
    """📚 Search the UNSW Library catalog.

    Opens the Primo search in your browser (since the catalog
    is a JavaScript app and doesn't provide a CLI-friendly API).
    """
    from unsw.modules.library import LibraryModule

    module = LibraryModule()
    url = module.search(query, open_browser=open_browser)

    if not open_browser:
        print_info("Tip: Use --open / -o to open in your browser automatically.")


@library_app.command()
def links():
    """🔗 Show useful library links."""
    from unsw.modules.library import LibraryModule

    module = LibraryModule()
    links = module.get_useful_links()
    format_output(
        links,
        columns=["name", "url"],
        title="🔗 Useful Library Links",
    )


# ──────────────────────────────────────────────
# myUNSW commands
# ──────────────────────────────────────────────


@myunsw_app.command()
def login():
    """🎓 Log into myUNSW via browser (auto-capture session).

    [DEPRECATED] Prefer `unsw login --platform myunsw --browser`.
    """
    _deprecation_hint("unsw myunsw login", "unsw login --platform myunsw --browser")
    from unsw.auth.myunsw import login_via_browser

    config = Config()
    success = login_via_browser(config)
    if success:
        print_success("myUNSW login configured!")


@myunsw_app.command()
def courses(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """🎓 List your currently enrolled courses."""
    from unsw.modules.myunsw import MyUNSWModule

    config = Config()
    module = MyUNSWModule(config)
    if not module.client:
        return

    with console.status("Fetching enrolled courses..."):
        result = module.get_enrolled_courses()

    if not result:
        print_info(
            "No enrolled courses found or myUNSW not configured.\n"
            "Run: unsw login --platform myunsw --browser"
        )
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["code", "name", "term", "status"],
        title="Enrolled Courses",
        output_format=fmt,
    )


@myunsw_app.command()
def search(code: str):
    """🔍 Search for available classes by course code.

    Tries to scrape class data from myUNSW. If this doesn't work
    (myUNSW uses complex JavaScript), use --open to open the
    enrolment page in your browser.
    """
    from unsw.modules.myunsw import MyUNSWModule

    config = Config()
    module = MyUNSWModule(config)
    if not module.client:
        return

    with console.status(f"Searching classes for {code.upper()}..."):
        result = module.search_classes(code)

    if not result:
        print_info(
            f"Could not find class data for {code.upper()}.\n"
            "Opening myUNSW in your browser for manual search..."
        )
        module.open_class_search(code)
        return

    format_output(
        result,
        columns=["class_nbr", "section", "activity", "time", "day", "status", "enrols"],
        title=f"Available Classes: {code.upper()}",
    )


@myunsw_app.command()
def enrol(code: str, class_nbr: str):
    """📝 Enrol in a class.

    Opens myUNSW in your browser and provides instructions
    for enrolling in the specified class.
    """
    from unsw.modules.myunsw import MyUNSWModule

    module = MyUNSWModule(Config())
    print_info(f"Opening myUNSW to enrol in {code.upper()} (Class #{class_nbr})...")
    print_info("")
    print_info("  Steps to complete enrolment:")
    print_info("  1. Log into myUNSW if prompted")
    print_info(f"  2. Navigate to: Enrolment → Enrol in Classes")
    print_info(f"  3. Enter course code: {code.upper()}")
    print_info(f"  4. Enter Class Nbr: {class_nbr}")
    print_info(f"  5. Follow the prompts to complete enrolment")
    module.open_enrolment_page()


@myunsw_app.command()
def drop(code: str):
    """🗑️ Drop a course.

    Opens myUNSW in your browser and provides instructions
    for dropping the specified course.
    """
    from unsw.modules.myunsw import MyUNSWModule

    module = MyUNSWModule(Config())
    print_info(f"Opening myUNSW to drop {code.upper()}...")
    print_info("")
    print_info("  Steps to drop a course:")
    print_info("  1. Log into myUNSW if prompted")
    print_info("  2. Navigate to: Enrolment → Drop Classes")
    print_info(f"  3. Select {code.upper()} to drop")
    print_info(f"  4. Confirm the drop request")
    module.open_enrolment_page()


@myunsw_app.command()
def timetable(json_output: bool = typer.Option(False, "--json", help="Output as JSON")):
    """📅 View your personal class timetable from myUNSW.

    Shows your enrolled classes with days, times and locations
    as recorded in myUNSW (not the public timetable).
    """
    from unsw.modules.myunsw import MyUNSWModule

    config = Config()
    module = MyUNSWModule(config)
    if not module.client:
        return

    with console.status("Fetching your class timetable..."):
        result = module.get_timetable()

    if not result:
        print_info(
            "Could not fetch timetable from myUNSW.\n"
            "Opening myUNSW in your browser as fallback..."
        )
        module.open_timetable_page()
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["course", "activity", "section", "day", "time", "location", "weeks"],
        title="My Class Timetable",
        output_format=fmt,
    )


@myunsw_app.command()
def grades(
    term: Optional[str] = typer.Option(
        None,
        "--term",
        "-t",
        help="Term code (e.g. 5266 for T2 2026). Omit to fetch all known terms.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """🎓 View your academic results from myUNSW.

    Without --term, fetches grades for all known recent terms.
    """
    from unsw.modules.myunsw import MyUNSWModule

    config = Config()
    module = MyUNSWModule(config)
    if not module.client:
        return

    with console.status("Fetching grades..."):
        result = module.get_grades(term=term)

    if not result:
        print_info("No grades found or myUNSW not configured.")
        return

    fmt = "json" if json_output else "table"
    format_output(
        result,
        columns=["term", "code", "name", "mark", "grade"],
        title="Academic Results",
        output_format=fmt,
    )


@myunsw_app.command()
def open():
    """🌐 Open myUNSW in your browser."""
    from unsw.modules.myunsw import MyUNSWModule

    module = MyUNSWModule(Config())
    module.open_enrolment_page()


# ──────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────


def _deprecation_hint(old: str, new: str) -> None:
    """Print a one-line deprecation hint to stderr for an alias command."""
    import os

    # Gated by env var so the message doesn't spam real users by default
    if os.environ.get("UNSW_CLI_SHOW_DEPRECATION"):
        print_warning(f"Deprecated: `{old}` — use `{new}` instead.")


def _show_config(config: Config) -> None:
    """Display current configuration."""
    lines = [
        "## Current Configuration",
        "",
        f"**zID**: {config.auth.zid or 'Not set'}",
        f"**zPass**: {'✅ Set' if config.auth.zpass else 'Not set'}",
        f"**Moodle Cookie**: {'✅ Set' if config.load_cookies().get('MoodleSession') else 'Not set'}",
        "",
        f"**Cookie file**: {CONFIG_DIR / 'cookies.json'}",
        f"**Cookies stored**: {list(config.load_cookies().keys())}",
        f"**Config file**: {CONFIG_FILE}",
        "",
        f"**Output format**: {config.display.format}",
    ]
    print_panel("⚙️  Configuration", "\n".join(lines))


def _do_login(
    zid: Optional[str],
    zpass: Optional[str],
    set_cookie: Optional[str],
    show: bool,
) -> None:
    """Shared login logic used by both `unsw login` and `unsw auth login`.

    Without any flags, runs the interactive wizard for all platforms.
    With flags, saves and verifies each specified credential.
    """
    config = Config()
    changed_any = False

    if show:
        _show_config(config)
        return

    if zid:
        config.auth.zid = zid
        changed_any = True

    if zpass:
        config.auth.zpass = zpass
        changed_any = True

    if set_cookie:
        if "=" in set_cookie:
            key, value = set_cookie.split("=", 1)
            cookies = config.load_cookies()
            cookies[key] = value
            config.save_cookies(cookies)
            print_success(f"Cookie '{key}' saved")
            changed_any = True
        else:
            print_error("Invalid cookie format. Use: Name=Value")

    # ── Interactive mode: check status first, then prompt for each platform ──
    if not any([zid, zpass, set_cookie, show]):
        print_panel(
            "🔐 UNSW Login",
            "Checking current login status for all platforms...\n"
            "Already authenticated platforms can be skipped.\n",
        )

        # ── Pre-check all platforms ──
        from unsw.auth.moodle import verify_cookie
        from unsw.auth.myunsw import verify_session
        from unsw.auth.webcms3 import verify_credentials

        saved_cookies = config.load_cookies()
        moodle_cookie_val = (
            saved_cookies.get("MoodleSession") or config.auth.moodle_session_cookie
        )
        myunsw_has_cookies = any(k.startswith("myunsw_") for k in saved_cookies)

        webcms3_already_ok = bool(
            config.auth.zid and config.auth.zpass
        ) and verify_credentials(config.auth.zid, config.auth.zpass)
        moodle_already_ok = bool(moodle_cookie_val) and verify_cookie(moodle_cookie_val)
        myunsw_already_ok = myunsw_has_cookies and verify_session(config)

        print()

        # ── Step 1: WebCMS3 (zID + zPass) ──
        print_info("Step 1/3: WebCMS3 (CSE course website)")
        if webcms3_already_ok:
            print_success(f"WebCMS3 already logged in as {config.auth.zid}")
            redo = typer.confirm("Re-login to WebCMS3?", default=False)
            if not redo:
                print_info("  Skipping WebCMS3.\n")
            else:
                webcms3_already_ok = False  # Force re-login

        if not webcms3_already_ok:
            print_info("Enter your zID and zPass to log into WebCMS3.\n")

            current_zid = config.auth.zid or ""
            new_zid = typer.prompt("zID", default=current_zid, show_default=True)
            if new_zid:
                config.auth.zid = new_zid
                changed_any = True

            current_zpass = config.auth.zpass or ""
            new_zpass = typer.prompt(
                "zPass",
                default="*****" if current_zpass else "",
                show_default=False,
                hide_input=True,
            )
            if new_zpass and new_zpass != "*****":
                config.auth.zpass = new_zpass
                changed_any = True

            # Save WebCMS3 credentials
            if changed_any:
                config.save()
                print_success("WebCMS3 credentials saved.\n")
                verify_config = Config()
                if not verify_config.auth.zid:
                    print_warning(
                        "Config may not have saved correctly. "
                        "Check ~/.config/unsw-cli/config.yaml"
                    )
                else:
                    print_info(f"Config verified: zID={verify_config.auth.zid}")

            # Verify WebCMS3 immediately
            if config.auth.zid and config.auth.zpass:
                print_info("Verifying WebCMS3...")
                ok = verify_credentials(config.auth.zid, config.auth.zpass)
                if ok:
                    print_success("WebCMS3 login verified!")
                else:
                    print_warning("WebCMS3 login failed. Check your zID and zPass.")

        print()

        # ── Steps 2 & 3: Unified SSO login (Moodle + myUNSW) ──
        # Both use Azure AD SSO, so we open the browser ONCE and walk through
        # both logins sequentially. The Azure AD session token is shared
        # between the two redirects, so subsequent logins are faster.
        sso_platforms_needed: list[str] = []

        if not moodle_already_ok:
            sso_platforms_needed.append("moodle")
        else:
            print_info("Step 2/3: Moodle — already logged in")

        if not myunsw_already_ok:
            sso_platforms_needed.append("myunsw")
        else:
            print_info("Step 3/3: myUNSW — already logged in")

        if sso_platforms_needed:
            names = "/".join(p.title() for p in sso_platforms_needed)
            print_info(f"Step 2/3 + 3/3: Unified SSO login for {names}")
            print_info(
                "Both Moodle and myUNSW use Microsoft Azure AD SSO.\n"
                "We'll open the browser ONCE — log into each in turn.\n"
            )

            redo_choice = typer.confirm("Open browser for SSO login?", default=True)
            if redo_choice:
                from unsw.auth.sso import sso_login_all

                results = sso_login_all(config, platforms=sso_platforms_needed)
                # Update the *_already_ok flags based on results
                if results.get("moodle"):
                    moodle_already_ok = True
                if results.get("myunsw"):
                    myunsw_already_ok = True

                # If any platform failed, let the user know how to retry
                failed = [p for p in sso_platforms_needed if not results.get(p)]
                if failed:
                    print()
                    print_warning(
                        f"Login did not complete for: {', '.join(failed)}.\n"
                        "  You can retry later with:\n"
                        + "\n".join(
                            f"    unsw login --platform {p} --browser" for p in failed
                        )
                    )

        print()
        print_success("Login setup complete!")
        print_info("Run 'unsw auth status' to see all platform statuses.")
        return

    # ── Non-interactive mode (flags provided): save & verify ──
    if changed_any:
        config.save()
        print_success("Configuration saved!")

    # Verify WebCMS3 after save
    if config.auth.zid and config.auth.zpass:
        print_info("Verifying WebCMS3 credentials...")
        from unsw.auth.webcms3 import verify_credentials

        ok = verify_credentials(config.auth.zid, config.auth.zpass)
        if ok:
            print_success("WebCMS3 login verified!")
        else:
            print_warning("WebCMS3 login failed. Check your zID and zPass.")

    # Verify Moodle cookie if present
    saved_cookies = config.load_cookies()
    moodle_cookie = (
        saved_cookies.get("MoodleSession") or config.auth.moodle_session_cookie
    )
    if moodle_cookie:
        from unsw.auth.moodle import verify_cookie

        ok = verify_cookie(moodle_cookie)
        if ok:
            print_success("Moodle session is valid.")
        else:
            print_warning("MoodleSession cookie has expired. Run: unsw login --browser")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────


def _do_moodle_browser_login() -> bool:
    """Helper: open browser for Moodle login.

    Returns True on success, False on failure/cancellation.
    """
    from unsw.auth.browser import moodle_login_via_browser

    config = Config()
    return moodle_login_via_browser(config)


def main():
    app()


if __name__ == "__main__":
    main()
