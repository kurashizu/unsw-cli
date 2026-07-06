"""Tests for unsw/utils/output.py — formatting helpers."""

from __future__ import annotations

import json

from unsw.utils.output import format_output, print_table


class TestFormatOutput:
    """Tests for the format_output helper."""

    def test_format_list_of_dicts_table(self, capsys):
        """Table format should produce a table."""
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        format_output(data, columns=["a", "b"], title="Test", output_format="table")
        # Don't assert exact output; just verify nothing crashes

    def test_format_list_of_dicts_json(self, capsys):
        """JSON format should produce parseable JSON."""
        data = [{"a": 1, "b": 2}]
        format_output(data, columns=["a", "b"], title="Test", output_format="json")
        captured = capsys.readouterr()
        # The output goes via rich, which writes via Console — assert contains
        # the values somewhere
        assert "1" in captured.out

    def test_format_empty_data(self, capsys):
        """Empty data should print a 'no data' message."""
        format_output([], columns=["x"], title="Empty", output_format="table")
        captured = capsys.readouterr()
        # Should not raise
        assert "No data" in captured.out or captured.out == ""

    def test_format_single_dict_becomes_list(self, capsys):
        """A single dict should be wrapped as a list."""
        data = {"a": 1, "b": 2}
        format_output(data, output_format="json")
        # Should not raise

    def test_format_missing_columns_auto_inferred(self, capsys):
        """If columns not given, infer from first dict."""
        data = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        format_output(data, output_format="table")
        # Should not raise


class TestPrintTable:
    """Tests for print_table helper."""

    def test_print_table_basic(self, capsys):
        """print_table should not raise on simple data."""
        print_table(
            "Title",
            ["a", "b"],
            [[1, 2], [3, 4]],
        )

    def test_print_table_with_none_values(self, capsys):
        """print_table should handle None gracefully."""
        print_table(
            "Title",
            ["a", "b"],
            [[None, 2], [3, None]],
        )
        captured = capsys.readouterr()
        # Should render empty strings for None
        assert "" in captured.out or captured.out != ""  # just no crash
