"""Output formatting utilities using Rich."""

from __future__ import annotations

import json
from typing import Any, Optional

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_table(
    title: str,
    columns: list[str],
    rows: list[list[Any]],
    *,
    style: str = "cyan",
) -> None:
    """Print data as a Rich table."""
    table = Table(title=title, box=box.ROUNDED, header_style=f"bold {style}")
    for col in columns:
        table.add_column(col, style=style)
    for row in rows:
        table.add_row(*[str(c) if c is not None else "" for c in row])
    console.print(table)


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    console.print_json(json.dumps(data, indent=2, default=str))


def print_info(message: str) -> None:
    """Print an informational message."""
    console.print(f"[blue]ℹ[/blue] {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]✓[/green] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[red]✗[/red] {message}")


def print_panel(title: str, content: str, style: str = "blue") -> None:
    """Print content in a styled panel."""
    panel = Panel(
        Markdown(content),
        title=title,
        border_style=style,
    )
    console.print(panel)


def format_output(
    data: list[dict[str, Any]] | dict[str, Any],
    columns: Optional[list[str]] = None,
    title: str = "",
    output_format: str = "table",
) -> None:
    """Format output based on the configured or requested format."""
    if output_format == "json":
        print_json(data)
        return

    if isinstance(data, dict):
        data = [data]

    if not data:
        print_info("No data to display.")
        return

    if columns is None and data:
        columns = list(data[0].keys())

    rows = []
    for item in data:
        rows.append([item.get(col, "") for col in columns])

    print_table(title, columns, rows)


def print_error_details(msg: str, details: str = "") -> None:
    """Print an error with optional details."""
    console.print(f"[red]✗ {msg}[/red]")
    if details:
        console.print(f"[dim]{details}[/dim]")
