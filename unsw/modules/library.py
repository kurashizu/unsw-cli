"""Library module - search and access library.unsw.edu.au resources.

The library catalog (Primo) is a single-page application that loads results
dynamically via JavaScript. Since there's no public JSON API we can easily
access from the CLI, we provide:
1. A search URL that opens in the browser (via webbrowser module)
2. A listing of useful library links and resources
"""

from __future__ import annotations

import webbrowser
from typing import Any, Optional

from unsw.modules.base import BaseModule
from unsw.utils.output import print_info

PRIMO_BASE = "https://primoa.library.unsw.edu.au"


class LibraryModule(BaseModule):
    """Access UNSW Library resources."""

    name = "library"
    description = "UNSW Library - search catalog and find resources"

    def search(
        self,
        query: str,
        max_results: int = 20,
        open_browser: bool = False,
    ) -> str:
        """Search the library catalog.

        Since Primo (the library catalog) is a JavaScript SPA,
        returns a URL the user can open in their browser.

        If open_browser is True, opens the URL automatically.
        """
        url = (
            f"{PRIMO_BASE}/discovery/search"
            f"?vid=61UNSW_INST:UNSWS"
            f"&tab=Everything"
            f"&query=any,contains,{query}"
            f"&offset=0"
            f"&limit={max_results}"
        )

        if open_browser:
            webbrowser.open(url)
            print_info(f"Opened in browser: {url}")
        else:
            print_info(f"Search URL: {url}")

        return url

    def get_useful_links(self) -> list[dict[str, str]]:
        """Get a list of useful library links."""
        return [
            {"name": "Library Home", "url": "https://www.library.unsw.edu.au/"},
            {
                "name": "Primo Search (Catalog)",
                "url": f"{PRIMO_BASE}/discovery/search?vid=61UNSW_INST:UNSWS",
            },
            {
                "name": "UNSWorks (Research Repository)",
                "url": "https://unsworks.unsw.edu.au/",
            },
            {
                "name": "Subject Guides",
                "url": "https://subjectguides.library.unsw.edu.au/",
            },
            {
                "name": "Course Reserves",
                "url": "https://primoa.library.unsw.edu.au/discovery/search?vid=61UNSW_INST:UNSWS&tab=CourseReserves",
            },
            {
                "name": "Bookings (Rooms/Study)",
                "url": "https://unswlibrary-bookings.libcal.com/",
            },
            {
                "name": "FAQs / Ask a Librarian",
                "url": "https://unswlibrary.libanswers.com/",
            },
            {
                "name": "Databases A-Z",
                "url": "https://subjectguides.library.unsw.edu.au/az.php",
            },
        ]
