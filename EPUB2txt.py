# EPUB2txt — convert EPUB books into Reboku Text Books (.txt)
# Copyright (C) 2026  Dino9021
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <https://www.gnu.org/licenses/>.

"""EPUB -> Reboku Text Book (.txt)

把 EPUB 轉成「在記事本裡讀起來舒服、閱讀器也能提供良好的體驗,同時還能大幅縮小體積」
的純文字書。
Convert an EPUB into a plain-text book that reads cleanly in Notepad, still gives a
reader something good to work with, and takes up a fraction of the space.

用法 / Usage:
    把 epub 檔或資料夾拖到本檔上放開      # drag & drop a file or a folder
    python EPUB2txt.py                    # no source -> opens the window (GUI)
    python EPUB2txt.py book.epub
    python EPUB2txt.py ./library -r -o ./out -f

輸出檔名與來源同名(book.epub -> book.txt);`-o` 加上資料夾來源時,來源的子資料夾
結構會照樣重建。一頁一圖的圖片型書籍(漫畫、掃描書)沒有可抽取的文字,會整批檢查
完再一次列出、不轉換(判定規則見 is_image_book)。
The output is named after the source file (book.epub -> book.txt); with `-o` on a
folder source the sub-folder structure of the source is mirrored. One-image-per-page
books (comics, scans) hold no text to extract, so they are checked as a batch and
reported once instead of converted (the rule lives in is_image_book).

輸出格式 / Output format (RTB-1) — 完整規範見 README.md,可執行的範例見
samples/(Sample.epub 轉出來就是 Sample.txt):
The full specification is in README.md; samples/ holds a runnable example —
converting Sample.epub reproduces Sample.txt byte for byte.

    Reboku Text Book 1
    Title: Aesop's Fables: A Selection
    Author: Aesop
    Language: en
    Cover: True

    --==# Contents #==--

    Introduction
    The Fox and the Grapes

    --==# Introduction #==--

    Aesop is an ancient teller of short tales, and this little book gathers ten
    of the most beloved ones.

    --==# The Fox and the Grapes #==--

    One warm afternoon a hungry fox trotted through an orchard and spotted a
    bunch of ripe grapes hanging high on a vine.

    Moral: It is easy to despise what you cannot have.

    --==[ Cover ]==--
    /9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof
    --==[ /Cover ]==--

只用 ASCII 標點、英文欄位名;`--==# 標題 #==--` 的 `#` 數量就是目次層級(1 個第一層、
2 個第二層…);封面是等比例縮到 200x300 以內的 JPEG,base64 寫在檔尾。
ASCII punctuation and English field names only; the number of `#` marks in
`--==# Title #==--` is the TOC depth (one = top level, two = one level in, ...);
the cover is a JPEG fitted inside 200x300, base64'd at the end of the file.

沒有必要的第三方相依:轉檔只用標準函式庫(zipfile / xml.etree / html.parser /
tkinter)。唯一的選用套件是 Pillow,只有要夾帶封面時才需要。
No required third-party dependency: the conversion uses the standard library
alone (zipfile / xml.etree / html.parser / tkinter). The single optional package
is Pillow, needed only to embed covers.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import posixpath
import queue
import re
import sys
import threading
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree

FORMAT_BANNER = "Reboku Text Book 1"
MAX_HEADING_LEVEL = 6

# ---------------------------------------------------------------- small helpers


def _local(tag: str) -> str:
    """`{http://...}package` -> `package` (namespace-agnostic tag matching)."""
    return tag.rsplit("}", 1)[-1].lower()


def _collapse(text: str) -> str:
    """Squeeze ASCII whitespace runs into one space; keep U+3000 (it separates a
    CJK title from its subtitle and must survive so labels stay comparable)."""
    return re.sub(r"[ \t\r\n\f\v]+", " ", text).strip()


def _norm(text: str) -> str:
    """Whitespace-insensitive comparison key."""
    return re.sub(r"\s+", "", text)


# An address worth writing into a text file: one that leads OUT of the book. A relative
# href is in-book navigation (a footnote, the contents page) — the .txt has no way to
# follow it and printing it would bury the prose in noise.
EXTERNAL_LINK = re.compile(r"^(https?|mailto|ftp|ftps|tel)\s*:", re.IGNORECASE)


# Query parameters that say nothing about *where* a link goes (owner 2026-07-29): the ad
# and analytics trackers a share button staples on, and the interface-language hints that
# would otherwise pin a Taiwanese reader's link to whatever locale the publisher browsed in.
# Everything else is kept — a query string is often the address itself (a search, a page
# number, a file id), and dropping it would break the link.
TRACKING_PARAMS = {
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "yclid", "twclid", "igshid", "igsh",
    "mc_cid", "mc_eid", "ref_src", "ref_url", "referrer", "s_kwcid", "spm", "share_id",
    "_ga", "_gl", "wt_mc", "trk", "trkCampaign",
    # interface language / locale
    "hl", "lang", "locale", "language", "lr", "ui_locales", "setlang",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_")


def _is_tracking(name: str) -> bool:
    key = name.strip().lower()
    return key in {p.lower() for p in TRACKING_PARAMS} or key.startswith(TRACKING_PREFIXES)


def _clean_url(href: str) -> str:
    """Strip tracking and locale parameters, keeping everything else byte for byte.

    Rebuilt by splitting on the separators rather than through urlencode, so a parameter
    that survives keeps exactly the percent-encoding the book wrote (re-encoding a link is
    a good way to break it).
    """
    base, hsep, fragment = href.partition("#")
    head, qsep, query = base.partition("?")
    if not qsep:
        return href
    # A `mailto:` query is not part of the address — it is a hint for the compose window
    # (`?subject=`, `?body=`, `?cc=`). In a text file it is noise, and keeping it also
    # stops the address matching the plain one the book printed beside it.
    if head.lower().startswith("mailto:"):
        return head + hsep + fragment
    kept = [p for p in query.split("&") if p and not _is_tracking(p.split("=", 1)[0])]
    return head + ("?" + "&".join(kept) if kept else "") + hsep + fragment


def _same_target(text: str, href: str) -> bool:
    """Does the link's own text already say its address? ("www.x.com/y" for
    "https://www.x.com/y/" does.) Then printing both just says it twice.

    The text is swept the same way the address is, so a book that prints the raw link —
    footnotes citing a source do this — matches its own href and ends up written **once,
    cleaned**, instead of twice: the tracker-laden version the book printed followed by
    the tidy one.
    """

    def key(value: str) -> str:
        # unquote first: a book that prints `service@x.com` alongside an href of
        # `mailto:service%40x.com` is saying the same thing twice, and without this it
        # gets written twice.
        plain = unquote(_clean_url(value.strip()))
        return re.sub(r"^(https?://|mailto:)", "", plain.lower()).rstrip("/")

    return key(text) == key(href)


# A line that is nothing but one address, e.g. 「<https://example.com/x>」.
LONE_LINK = re.compile(r"^<[a-z][a-z0-9+.-]*:[^>]*>$", re.IGNORECASE)

# `<hr>` — a book draws a line to separate scenes or to close a section. Twenty hyphens
# is the plain-text way of drawing it (owner 2026-07-29); the paragraph indent goes in
# front like any other line, which also keeps it away from column 0, where a run of
# dashes is the header block's closing rule.
HORIZONTAL_RULE = "-" * 20

ENTITY_DECL = re.compile(rb"<!ENTITY", re.IGNORECASE)


# Characters XML 1.0 forbids outright: the C0 controls other than tab/LF/CR, and the two
# non-characters at the end of the BMP. All of them are single bytes in UTF-8 except the last
# two, which are the three-byte sequences below.
_XML_FORBIDDEN = re.compile(
    rb"[\x00-\x08\x0b\x0c\x0e-\x1f]|\xef\xbf\xbe|\xef\xbf\xbf"
)


def _parse_xml(data: bytes):  # type: ignore[no-untyped-def]
    """ElementTree, but refuse documents that declare entities.

    XXE and billion-laughs both need an entity declaration, and no real EPUB
    package/NCX has one — rejecting them keeps this script dependency-free
    (defusedxml is not in the standard library) while closing both holes.

    Characters XML forbids are DROPPED rather than allowed to fail the parse. A real book
    carries a stray backspace in the middle of its author's name
    (`<dc:creator>J.K\\x08.羅琳</dc:creator>`), which is illegal in XML 1.0, so the package
    document would not parse and the entire book was lost — over one invisible byte. Losing
    that byte is the better trade, and it is the same call a reader has to make for a .txt it
    is handed: one invisible character is not worth a book.
    """
    if ENTITY_DECL.search(data[:65536]):
        raise ValueError("XML declares entities (refused)")
    return ElementTree.fromstring(_XML_FORBIDDEN.sub(b"", data))


def _zip_path(base: str, href: str) -> str:
    """Resolve an OPF-relative href to a zip entry name."""
    href = unquote(href)
    parts = (base + href).split("/")
    out: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


# ------------------------------------------------------------------------ CSS
#
# A book says "leave space here" in two ways, and until now this program only heard
# one of them (owner 2026-07-29). One is an empty paragraph, which _extract already
# counts. The other is the stylesheet: a quotation set in 楷體 with `margin-top:21px`
# above it is a visibly separate block on the page, and flattening it into the prose
# loses where the quotation starts and ends.
#
# What follows reads exactly enough CSS to answer two questions about a block:
# **which font is it set in** and **how much space does it ask for above and below**.
# It is deliberately NOT a CSS engine — no cascade layers, no descendant selectors,
# no percentages, no font-size resolution. Anything it cannot answer it reports as
# "not declared", which simply means no blank line is added: the failure mode is the
# output we already have, never mangled text.

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# `p`, `.text`, `p.text` — the shapes real books use for paragraph styling. A selector
# with a space, `>`, `[`, `:` or `#` in it is skipped rather than half-understood.
_SIMPLE_SELECTOR = re.compile(r"^([a-zA-Z][a-zA-Z0-9]*)?(?:\.([A-Za-z0-9_\-]+))?$")
# The class of the LAST simple part of a selector: `.hltr .gfont2B` -> `gfont2B`. Used only
# for the font-weight/size index (see `_Css._heavy`), never for anything that moves text.
_LAST_SIMPLE = re.compile(r"\.([A-Za-z0-9_\-]+)$")
# One em, in px. Resolving real font-size cascades would double the size of this file
# for a value that is 16px in almost every book; the threshold this feeds is half a
# line, so being a few px out cannot change the answer.
_EM_PX = 16.0


def _css_length(value: str) -> float | None:
    """A CSS length in px, or None when it is not a length this program understands."""
    m = re.match(r"^\s*(-?[\d.]+)\s*(px|em|rem|pt|pc|in|cm|mm)?\s*$", value or "")
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or ("px" if n == 0 else "")
    factor = {
        "px": 1.0, "em": _EM_PX, "rem": _EM_PX, "pt": 96 / 72,
        "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "": 1.0,
    }
    return n * factor[unit]


_SIDES = ("top", "right", "bottom", "left")


def _css_side(value: str, side: str) -> str:
    """One side's value out of a CSS box shorthand (`border-style: solid none none`).

    The shorthand is positional: one value is all four sides, two are top/bottom then
    left/right, three are top, left/right, bottom, four are clockwise from the top.
    Reading it as "the first word applies everywhere" turns `solid none none` — a line
    above only, which is how a book underlines a heading — into a box on all four sides.
    """
    parts = value.split()
    if not parts:
        return ""
    index = _SIDES.index(side)
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] if side in ("top", "bottom") else parts[1]
    if len(parts) == 3:
        return (parts[0], parts[1], parts[2], parts[1])[index]
    return parts[index]


def _font_key(value: str) -> str:
    """A font stack as a comparison key: lower case, no quotes, no stray spaces.

    So `Times,serif` and `"Times", serif` are the same stack (they are), while `serif`
    and `Times, serif` are different (they are). No attempt is made to decide that two
    *different* stacks would render alike — in CJK text `serif` and `sans-serif` very
    often do, because neither names a font that has Chinese in it and both fall back to
    the one CJK face the system has. That is why a font change is only ever allowed to
    add a blank line: at worst the book gains a break where it drew none.
    """
    return ",".join(part.strip().strip("\"'").lower() for part in value.split(",") if part.strip())


def _border_visible(get, side: str) -> bool:  # type: ignore[no-untyped-def]
    """Does one side of a box draw a visible line? `get(prop)` looks a property up.

    Taking a lookup function rather than reading an index directly is what lets the same
    reading serve both a whole element ([_Css.border]) and a styled inline run
    ([_Css.run_framed]), which are indexed separately and on purpose.

    A per-side property (`border-top-style`) beats the shorthand, and a shorthand is read
    positionally (see [_css_side]) — `border-style: none dashed` is a line at each END of the
    text and none above or below it. `none`, `hidden` and a zero width are not lines.

    `border:` on its own is width/style/colour, not a per-side list, so it applies as written
    to every side.
    """
    value = get(f"border-{side}")
    if value is None:
        value = get("border")
    style = get(f"border-{side}-style")
    if style is None:
        shorthand = get("border-style")
        style = _css_side(shorthand, side) if shorthand else None
    width = get(f"border-{side}-width")
    if width is None:
        shorthand = get("border-width")
        width = _css_side(shorthand, side) if shorthand else None
    if style and style.strip().lower() in ("none", "hidden"):
        return False
    if width is not None and width.strip() and _css_length(width.strip()) == 0:
        return False
    if value is None:
        return bool(style and style.strip().lower() not in ("none", "hidden"))
    words = value.strip().lower().split()
    if not words or "none" in words or "hidden" in words:
        return False
    return not all((_css_length(w) == 0) for w in words if _css_length(w) is not None) or any(
        w in ("solid", "dashed", "dotted", "double", "groove", "ridge") for w in words
    )


# A box needs a PAIR of opposite sides. One side on its own is the standard way to mark a
# quotation, not a frame — see [_Css.framed] for the book that proves it.
_OPPOSITE = (("top", "bottom"), ("left", "right"))


def _framed(visible, tag: str, classes: list[str]) -> bool:  # type: ignore[no-untyped-def]
    """Lines on two opposite sides? `visible(tag, classes, side)` answers per side."""
    return any(
        visible(tag, classes, one) and visible(tag, classes, other) for one, other in _OPPOSITE
    )


class _Css:
    """The declarations this program can use, indexed by (tag, class)."""

    WANTED = (
        "font-family", "margin", "margin-top", "margin-bottom",
        "border", "border-top", "border-bottom",
        "border-style", "border-top-style", "border-bottom-style",
        "border-width", "border-top-width", "border-bottom-width",
    )

    # Everything about the box, per side. The shorthands are read positionally (_css_side).
    BOX = tuple(
        [f"border-{side}{suffix}" for side in _SIDES for suffix in ("", "-style", "-width")]
        + ["border", "border-style", "border-width"]
    )

    # Read for the styled-run / block-appearance questions only ([heavier], [run_framed],
    # [run_size], [run_underlined], [run_centred], [run_indented]), and out of a WIDER set of
    # selectors — see `_run` below.
    RUN = ("font-size", "font-weight", "text-indent", "text-align",
           "text-decoration", "text-decoration-line") + BOX

    def __init__(self) -> None:
        # (tag, class) -> {property: value}; later rules win, class beats bare tag.
        self._by_tag: dict[str, dict[str, str]] = {}
        self._by_class: dict[str, dict[str, str]] = {}
        self._by_both: dict[tuple[str, str], dict[str, str]] = {}
        # class -> {font-size, font-weight, border*}, taken from the LAST simple part of ANY
        # selector, descendant selectors included — books routinely write `.vrtl .line02`,
        # keying the rule on the writing direction, and the rest of this class deliberately
        # skips a selector it cannot understand whole.
        #
        # ⚠️ A SEPARATE index on purpose, and it is asked ONLY about a styled inline run whose
        # text is a whole line ([heavier], [run_framed]). Feeding these selectors into
        # `declared()` instead would change how fonts, margins and the `----` rules are read
        # for EVERY book; here a wrong answer can only mis-style one line, and can never move
        # text or spacing. DO NOT wire `_run` into `declared()` / `edges()` / `margins()`.
        self._run: dict[str, dict[str, str]] = {}

    def add(self, text: str) -> None:
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _CSS_COMMENT.sub("", text)):
            decls = {}
            run = {}
            for decl in body.split(";"):
                if ":" in decl:
                    key, value = decl.split(":", 1)
                    key = key.strip().lower()
                    if key in self.WANTED:
                        decls[key] = value.strip()
                    if key in self.RUN:
                        run[key] = value.strip()
            for selector in selectors.split(","):
                selector = selector.strip()
                if run:
                    # `.hltr .gfont2B` and `.vrtl .gfont2B` both say the same thing about
                    # `.gfont2B`; the ancestor only picks the writing direction.
                    last = _LAST_SIMPLE.search(selector.replace(">", " ").strip())
                    if last and last.group(1):
                        self._run.setdefault(last.group(1), {}).update(run)
                if not decls:
                    continue
                m = _SIMPLE_SELECTOR.match(selector)
                if not m:
                    continue
                tag, cls = (m.group(1) or "").lower(), m.group(2)
                if tag and cls:
                    self._by_both.setdefault((tag, cls), {}).update(decls)
                elif cls:
                    self._by_class.setdefault(cls, {}).update(decls)
                elif tag:
                    self._by_tag.setdefault(tag, {}).update(decls)

    def heavier(self, classes: list[str]) -> bool:
        """Does the stylesheet set this run bigger than the body text, or bold?

        Only ever asked about a run that makes up the WHOLE of a document's first line
        (see [_sub_headings]), which is why "bigger or bolder" is enough here and is
        nowhere near enough on its own: several books in the sample library set their
        classical-Chinese quotations in exactly the same larger bold face, and asking this
        of every line called 940 of them headings, most of them poems.
        """
        for cls in classes:
            declared = self._run.get(cls, {})
            weight = declared.get("font-weight", "").strip().lower()
            if weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600):
                return True
            size = declared.get("font-size", "").strip().lower()
            if size.endswith("%"):
                try:
                    if float(size[:-1]) > 100:
                        return True
                except ValueError:
                    pass
            else:
                length = _css_length(size) if size else None
                if length is not None and length > _EM_PX:
                    return True
        return False

    def declared(self, tag: str, classes: list[str], prop: str) -> str | None:
        """The winning value of one property for this element, or None."""
        for cls in reversed(classes):
            hit = self._by_both.get((tag, cls), {}).get(prop) or self._by_class.get(cls, {}).get(prop)
            if hit is not None:
                return hit
        return self._by_tag.get(tag, {}).get(prop)

    def font(self, chain: list[tuple[str, list[str]]]) -> str:
        """The font this block ends up in — its own, else the nearest ancestor's."""
        for tag, classes in reversed(chain):
            value = self.declared(tag, classes, "font-family")
            if value:
                return _font_key(value)
        return ""

    def border(self, tag: str, classes: list[str], side: str) -> bool:
        """Does this element draw a visible border on one side? See [_border_visible]."""
        return _border_visible(lambda prop: self.declared(tag, classes, prop), side)

    def run_size(self, classes: list[str]) -> float | None:
        """The font-size these classes declare, in em, or None when they declare none."""
        for cls in reversed(classes):
            value = self._run.get(cls, {}).get("font-size", "").strip().lower()
            if not value:
                continue
            if value.endswith("%"):
                try:
                    return float(value[:-1]) / 100
                except ValueError:
                    return None
            length = _css_length(value)
            return None if length is None else length / _EM_PX
        return None

    def run_has(self, classes: list[str], prop: str, wanted: str) -> bool:
        """Does any of these classes declare `prop` with `wanted` in its value?"""
        return any(wanted in self._run.get(cls, {}).get(prop, "").strip().lower()
                   for cls in classes)

    def run_indented(self, classes: list[str]) -> bool:
        """Does the stylesheet give this block a first-line indent of its own?"""
        for cls in classes:
            value = self._run.get(cls, {}).get("text-indent", "").strip()
            if value and _css_length(value) not in (None, 0):
                return True
        return False

    def run_framed(self, classes: list[str]) -> bool:
        """Is there a line on any side of this styled inline run?

        Same question as [framed], asked of the wider `_run` index. Books mark a sub-heading
        `<span class="big"><span class="bar">…</span></span>` and then declare the border keyed
        on the writing direction — `.vrtl .bar { border-style: none double none double }` — a
        descendant selector the rest of this class cannot read. Without this, one sample book's
        sub-heading came out as a heading on the single page where it happened to be the
        document's first line, and as ordinary text on the other fifteen.
        """
        for cls in classes:
            declared = self._run.get(cls, {})
            if declared and any(_border_visible(declared.get, side) for side in _SIDES):
                return True
        return False


    def edges(self, tag: str, classes: list[str]) -> tuple[bool, bool]:
        """(line above, line below) — does this block draw a visible top/bottom border?

        A book draws the same line two ways and they look identical on the page: `<hr/>`,
        and a border on the box around a passage. In one sample book a single class puts a
        line above and below every glossary panel: 198 of that book's ~242 drawn lines are
        borders, and only the 44 real `<hr/>` were coming out.

        `border:` on its own means a box, which is a line above AND below.
        """
        return self.border(tag, classes, "top"), self.border(tag, classes, "bottom")

    def framed(self, tag: str, classes: list[str]) -> bool:
        """Is this element in a box of its own — lines on two OPPOSITE sides?

        Left and right count as much as top and bottom: a heading marked out by a rule at each
        end of the words is framed just as much as one with a line above and below, and in a
        vertically-set book the two are literally the same declaration.

        ⚠️ A line on ONE side is NOT a frame, and the difference is not pedantry. A single
        border is the universal way to mark a QUOTATION. One sample book sets its quotations
        `border-style: none none none dotted` and its sub-headings
        `border-style: none double none double` — same book, same colour. Reading "any side" as
        a frame turned 220 of that book's quotations into boxed headings, some of them 200
        characters long. DO NOT relax this back to `any`.
        """
        return _framed(lambda tag_, classes_, side: self.border(tag_, classes_, side), tag, classes)

    def run_framed(self, classes: list[str]) -> bool:
        """Is this styled inline run in a box of its own? Same pair rule as [framed].

        Asked of the wider `_run` index, because books routinely key the declaration on the
        writing direction, which the rest of this class cannot read.
        """
        return any(
            _framed(lambda _t, cls, side: _border_visible(self._run.get(cls[0], {}).get, side),
                    "", [cls])
            for cls in classes
            if self._run.get(cls)
        )

    def margins(self, tag: str, classes: list[str]) -> tuple[float, float]:
        """(top, bottom) in px. Margins do not inherit, so only this element counts."""
        top = bottom = 0.0
        shorthand = self.declared(tag, classes, "margin")
        if shorthand:
            parts = shorthand.split()
            first = _css_length(parts[0]) if parts else None
            third = _css_length(parts[2]) if len(parts) > 2 else first
            top = first or 0.0
            bottom = third if third is not None else top
        for prop, index in (("margin-top", 0), ("margin-bottom", 1)):
            value = self.declared(tag, classes, prop)
            length = _css_length(value) if value else None
            if length is not None:
                if index == 0:
                    top = length
                else:
                    bottom = length
        return top, bottom


# How much more space than this book's ordinary paragraph gap counts as "the book left
# a gap here": half a line. Half a line is already visible, and every real case in the
# sample library (21px above a quotation, 1rem below its attribution) clears it easily.
GAP_THRESHOLD_PX = _EM_PX / 2


def _extra_blanks(
    chain_of: list[list[tuple[str, list[str]]]],
    owners: list[int],
    css: _Css,
) -> list[int]:
    """Where the stylesheet says the book left a gap: 1 for a blank line, else 0.

    Two signals, ONE blank line (owner 2026-07-29 — they are two reasons for the same
    decision, not two decisions):

      * the font changed from the paragraph before, or
      * the gap between the two is wider than this book's ordinary paragraph gap.

    The blank goes in FRONT of the paragraph that changed and nowhere else. Putting one
    on both sides of a block would double up at the far edge, where the paragraph that
    changes back would ask for its own.

    The "ordinary gap" is measured from the document itself — the most common gap
    between consecutive paragraphs — so a book that gives every paragraph a margin has
    no unusual gaps at all, and nothing is added. Headings reset the comparison: they
    become chapter markers, which already stand alone.

    ⚠️ Two lines out of the SAME element are never compared. A poem is very often one
    `<p>` with `<br/>` between its verses (a real sample book is): those are separate
    lines here but one box on the page, with no margin between them at all. Comparing
    them as if they were neighbouring paragraphs put a blank line between every single
    verse — caught on the real book, which is why the identity is tracked at all.
    """
    heading = {"h1", "h2", "h3", "h4", "h5", "h6"}
    styles: list[tuple[str, float, float, bool] | None] = []
    for chain in chain_of:
        if not chain:
            styles.append(None)
            continue
        tag, classes = chain[-1]
        top, bottom = css.margins(tag, classes)
        styles.append((css.font(chain), top, bottom, tag in heading))

    # CSS collapses adjacent vertical margins to the larger of the two.
    def comparable(i: int) -> bool:
        here, before = styles[i], styles[i - 1]
        if not here or not before or here[3] or before[3]:
            return False
        return owners[i] != owners[i - 1]  # same element: no margin between its lines

    gaps: list[float | None] = [None] * len(styles)
    for i in range(1, len(styles)):
        if comparable(i):
            gaps[i] = max(styles[i - 1][2], styles[i][1])  # type: ignore[index]
    measured = [g for g in gaps if g is not None]
    ordinary = max(set(measured), key=measured.count) if measured else 0.0

    out = [0] * len(styles)
    for i in range(1, len(styles)):
        if not comparable(i):
            continue
        here, before = styles[i], styles[i - 1]
        assert here and before
        wider = gaps[i] is not None and gaps[i] - ordinary >= GAP_THRESHOLD_PX
        if here[0] != before[0] or wider:
            out[i] = 1
    return out


# ------------------------------------------------------------------- footnotes
#
# A footnote is one of the few things an EPUB states in the STANDARD's own words rather than
# in a stylesheet, so none of this guesses: EPUB 3 marks the note with
# `epub:type="footnote"` (or `endnote`/`rearnote`), its reference with `epub:type="noteref"`
# or `rel="footnote"`, and the DPUB-ARIA vocabulary says the same thing with
# `role="doc-endnote"` / `role="doc-noteref"` / `role="doc-backlink"`.
#
# Of the six books in the sample library that have notes at all, one declares the reference
# too (213 of them) and four leave the reference an ordinary internal
# link — for those the reference is recognised by WHERE IT POINTS: at a note, or at something
# inside one. 523 of the library's 526 notes resolve that way; the three that do not
# have no reference in the text at all and are left alone.
_NOTE_TYPES = ("footnote", "endnote", "rearnote")
_NOTE_ROLES = ("doc-footnote", "doc-endnote", "doc-note")
# The PLURAL words mark the notes AREA — a collection of notes, not one note. Books that mark
# the area but not the individual notes are common (`<section epub:type="endnotes"><ol><li
# id="footnote-007">`), so the area is what says "everything in here is a note".
_NOTE_AREAS = ("footnotes", "endnotes", "rearnotes")
_NOTE_AREA_ROLES = ("doc-footnotes", "doc-endnotes", "doc-rearnotes")


def _is_note_area(values: dict[str, str]) -> bool:
    """Is this element the container a book keeps its notes in?"""
    tokens = set()
    for attr in ("epub:type", "role"):
        tokens.update((values.get(attr) or "").lower().split())
    return bool(tokens.intersection(_NOTE_AREAS) or tokens.intersection(_NOTE_AREA_ROLES))


def _is_note_element(values: dict[str, str]) -> bool:
    """Is this element ONE note (not the container the notes sit in)?

    ⚠️ The vocabulary words are matched as WHOLE TOKENS, never as substrings. The plural
    `epub:type="endnotes"` / `role="doc-endnotes"` is the notes AREA, and `"endnote" in
    "endnotes"` is true — so a substring test opened a note on the container, left it open
    across every note inside it, and every one of them took the FIRST note's number. Caught on
    a book whose two notes both came out as 「註[1]」 (owner 2026-07-30).
    """
    tokens = set()
    for attr in ("epub:type", "role", "rel"):
        tokens.update((values.get(attr) or "").lower().split())
    return bool(tokens.intersection(_NOTE_TYPES) or tokens.intersection(_NOTE_ROLES))


def _note_word(language: str) -> str:
    """The word this book's own language uses to introduce a note.

    The label goes into the text as text, so it has to read naturally in the book it lands
    in — the same reason [_contents_word] exists. Anything not listed gets the English word,
    which is plain but never wrong.
    """
    code = (language or "").lower().replace("_", "-")
    if code.startswith("ja"):
        return "注"
    if code.startswith("ko"):
        return "주"
    if code.startswith("zh"):
        return "注" if any(tag in code for tag in ("hans", "-cn", "-sg", "-my")) else "註"
    return "Note"


# Every word the line above can produce. Used to keep the label from saying it twice —
# see [_note_label].
_NOTE_PREFIXES = ("註", "注", "주", "Note", "note")

# What a book puts between its own note marker and the note. Since the label written here
# replaces that marker, the separator goes with it — see the note branch in [_BlockText._flush].
NOTE_SEPARATORS = "：:、．.，,)）]】"

# A marker this program wrote into a sentence, with whatever space happens to sit around it.
# Used to give every one of them ONE space on each side — see [_space_note_marks].
_MARK_IN_TEXT = re.compile(r"[ 　]*(\((?:註|注|주|Note)\[[^\]\n]{1,16}\]\))[ 　]*")


# Punctuation that CLOSES what came before it, so it sits tight against it and takes no space
# in front (owner 2026-07-31). A closed set, like every other character list in this file — not
# 「looks like punctuation」, not 「is full-width」.
_TIGHT_AFTER = frozenset("。，、；：？！…—．" "」』）】〉》〕｝" ",.;:?!)]}")


def _space_note_marks(text: str) -> str:
    """One space each side of a note marker — never two, and none where one would look wrong.

    ⚠️ Run on the FINISHED line, not where the marker is written: what follows it decides
    whether a space belongs there, and that text does not exist yet when the reference's `</a>`
    closes. Doing it here also means the two ways a marker is written — replacing the book's own
    number, or appended after the words it explains — end up spaced identically.

    The space AFTER is dropped when the next character closes the sentence or the clause
    (`_TIGHT_AFTER`): CJK typography sets 「。」「，」「」」 hard against the word before them, and a
    space there reads as a hole in the sentence. Measured before deciding — **2,355 of the
    library's 5,403 markers** are followed by one of these, so it is the common case rather than
    an edge case. The space BEFORE is always kept: that is the side separating the marker from
    the words it belongs to.

    ⚠️ Only ever called for a line this program actually put a marker on (see `_wrote_mark`).
    A book is free to print 「(註[2])」 as its own text, and that text is the author's to space.
    """
    def spaced(m: "re.Match[str]") -> str:
        after = text[m.end():m.end() + 1]
        return f" {m.group(1)}" + ("" if after and after in _TIGHT_AFTER else " ")

    return _MARK_IN_TEXT.sub(spaced, text).strip()

# Brackets a book may already have put round its own marker. The label written here supplies
# its own, so a marker printed 「[1]」 would otherwise come out 「註[[1]]」 — 403 of those across
# the sample library (owner 2026-07-30). Stripped ONLY when the pair wraps the whole marker.
NOTE_BRACKETS = (("[", "]"), ("［", "］"), ("(", ")"), ("（", "）"), ("〔", "〕"), ("【", "】"),
                 ("〈", "〉"), ("<", ">"))

# What a note's marker is allowed to be made of (owner 2026-07-30): digits in any of the
# notations books use, plus the classic footnote symbols. A real note is NUMBERED — that is
# what tells it apart from a link on a WORD, which points at an explanation rather than
# carrying a note of its own.
#
# ⚠️ A closed set of characters, not a length or a look. CJK numerals are deliberately NOT
# here: 「十」 is a number and also a word, and there is no way to tell which one a book meant.
# Every character listed is either a digit or a mark that has no meaning as a word \u2014 which is
# why the full-width digits and the asterisk family belong (a book in the test library marks its
# dedication line with `\u273d` and hangs a note on it) while \u300c\u5341\u300d still does not.
_MARKER_CHARS = frozenset(
    "0123456789*.-\u2013\u2014#\u2020\u2021\u00a7\u00b6"
    "\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19"  # full-width \uff10-\uff19
    "\uff0a\u203b\u273d\u2731\u2217\ufe61"  # \uff0a \u203b \u273d \u2731 \u2217 \ufe61
    "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
    "\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467\u2468\u2469"
    "\u246a\u246b\u246c\u246d\u246e\u246f\u2470\u2471\u2472\u2473"
    "\u2474\u2475\u2476\u2477\u2478\u2479\u247a\u247b\u247c\u247d"
)


def _marker_core(shown: str) -> str:
    """What a reference shows, with the book's own word and brackets taken off.

    Both come off, in whichever order the book put them: 「（註1）」 is one real book's way of
    writing the marker 1, and taking only the brackets off left 「註1」 — which then read as
    words rather than a number, and came out as 註[註1] (29 notes in one book).
    """
    text = shown.strip()
    while True:
        before = text
        for prefix in _NOTE_PREFIXES:
            if text.startswith(prefix) and text[len(prefix):].strip():
                text = text[len(prefix):].strip()
                break
        for opening, closing in NOTE_BRACKETS:
            if text.startswith(opening) and text.endswith(closing) and len(text) > 2:
                text = text[1:-1].strip() or text
                break
        if text == before:
            return text


def _is_marker(shown: str) -> bool:
    """Is this the NUMBER of a note, rather than a word that links to an explanation?

    ⚠️ INTENTIONAL — **DO NOT answer this with a length, a superscript, or 「it looks like a
    number」.** The test is membership of [_MARKER_CHARS], a closed set: every character of what
    the reference shows has to be in it. Guessing from appearance is how this kind of code goes
    wrong, and here it would decide whether the reader's own words survive: one book's references
    read as a two-word phrase followed by a digit — it ends in a number and is still words. A
    reference that fails this test is not rejected; it takes the ★ road instead.
    """
    core = _marker_core(shown)
    return bool(core) and all(ch in _MARKER_CHARS for ch in core)


def _note_label(word: str, shown: str) -> str:
    """`註[2]` — and never `註[註1]` (owner 2026-07-30).

    Some books print the word in the reference itself, marking a footnote 「註1」, so wrapping
    that verbatim would give 註[註1]. The prefix comes off by **exact string
    comparison** against the words [_note_word] can produce — no pattern, no "looks like a
    note marker" test — and only when something is left after it (see [_marker_core]).
    """
    return f"{word}[{_marker_core(shown)}]"


def _anchor_key(doc: str, href: str) -> str:
    """`chapter_6.xhtml#foot-5-1` seen from `OEBPS/chapter_4.xhtml` -> `OEBPS/chapter_6.xhtml#foot-5-1`.

    One key for the whole book, because a note and its reference are very often in different
    documents (one sample book puts every note in the chapter AFTER the one citing it).
    """
    path, _, fragment = href.partition("#")
    base = posixpath.dirname(doc)
    target = _zip_path(base + "/" if base else "", path) if path else doc
    return f"{target}#{fragment}"


class _NoteScan(HTMLParser):
    """One document's share of the book-wide footnote index (see [_note_index]).

    Collects the ids that live on or inside a note element, and every internal `<a>` with
    the text it shows. Nothing is decided here — which links are references cannot be known
    until every document has been read.
    """

    def __init__(self, doc: str) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.note_ids: set[str] = set()
        # One entry per internal <a>, in document order:
        #   (target key, the text it shows, declared itself a noteref,
        #    the ids ON or INSIDE it, the index of the line it sits on)
        # The ids are what makes a MUTUAL pair visible: a note's way home points at the id
        # the reference carries, and books put that id on a <span> inside the link as often
        # as on the link itself. The line index answers "is this link the whole line?" — a
        # contents entry is, and a contents list linking to a chapter that links back is
        # mutual too, so that gate is what keeps a table of contents out of this.
        self.links: list[tuple[str, str, bool, list[str], int]] = []
        self.lines: list[str] = []
        # The ids inside ONE note element, one list per note. A book can point two references at
        # one note: its first line names two related words and carries an id on each, so both
        # references mean the same note — which is what lets them share a ★ number
        # (see [_note_index]).
        self.note_groups: list[list[str]] = []
        self._note_depth: list[int] = []  # len(_open) at which a note element opened
        self._open: list[str] = []
        self._block_ids: list[str] = []  # the id of each open block element, or ""
        self._group_depth: list[int] = []  # len(_open) at which each note ELEMENT opened
        self._group_at: list[int] = []  # where in note_groups each of those is kept
        self._link: list | None = None  # [target, declared, ids, buffer position]
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        values = dict(attrs)
        marks = " ".join((values.get("epub:type", ""), values.get("role", ""),
                          values.get("rel", ""))).lower()
        if tag in _BlockText.BLOCK or tag == "br":
            self._flush()
        if tag in _BlockText.BLOCK and tag != "hr":
            self._open.append(tag)
            self._block_ids.append(values.get("id") or "")
            if _is_note_element(values):
                self._group_depth.append(len(self._open))
                self._group_at.append(len(self.note_groups))
                self.note_groups.append([])
            if _is_note_element(values) or _is_note_area(values):
                self._note_depth.append(len(self._open))
        if self._note_depth and values.get("id"):
            self.note_ids.add(f"{self.doc}#{values['id']}")
            if self._group_at:
                self.note_groups[self._group_at[-1]].append(f"{self.doc}#{values['id']}")
        href = (values.get("href") or "").strip()
        if tag == "a" and href and not EXTERNAL_LINK.match(href):
            self._link = [_anchor_key(self.doc, href),
                          "noteref" in marks or "footnote" in marks, [], len(self._buf)]
        if self._link is not None and values.get("id"):
            self._link[2].append(f"{self.doc}#{values['id']}")

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        self.handle_starttag(tag, attrs)
        if tag in _BlockText.BLOCK and tag != "hr" and self._open:
            self._close_block()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link:
            key, declared, ids, start = self._link
            text = _collapse("".join(self._buf[start:]))
            # The id that names a note is as often on the block holding the link back into the
            # text as on the link itself: `<p id="the-note"><a href="#the-ref">1</a> …the note…`.
            # Without the block's id that note has no visible way home and the pair is missed.
            if self._block_ids and self._block_ids[-1]:
                ids = ids + [f"{self.doc}#{self._block_ids[-1]}"]
            self.links.append((key, text, declared, ids, len(self.lines)))
            self._link = None
        if tag in _BlockText.BLOCK and tag != "hr" and self._open:
            self._flush()
            self._close_block()

    def _close_block(self) -> None:
        self._open.pop()
        self._block_ids.pop()
        while self._note_depth and self._note_depth[-1] > len(self._open):
            self._note_depth.pop()
        while self._group_depth and self._group_depth[-1] > len(self._open):
            self._group_depth.pop()
            self._group_at.pop()

    def handle_data(self, data: str) -> None:
        self._buf.append(data)

    def _flush(self) -> None:
        text = _collapse("".join(self._buf))
        self._buf = []
        if text:
            self.lines.append(text)


def _note_index(
    book: "Epub", docs: list[str],
) -> tuple[set[str], dict[str, str], dict[str, int]]:
    """(anchor keys that belong to a note, anchor key -> its reference's text,
    anchor key -> its ★ number).

    Read BEFORE any of the book is written, so a note can be labelled with the number the
    text actually printed next to it even when the two are in different documents.

    Two shapes of footnote are found here. The first declares itself, in EPUB 3 or
    DPUB-ARIA vocabulary, and needs no guessing. The second declares nothing at all — and
    is still structural, because a footnote and its reference POINT AT EACH OTHER: the
    reference links to the note's id and the note links back to the reference's id. That
    mutual pair is the entry test (owner 2026-07-30).

    ⚠️ INTENTIONAL — **DO NOT drop the inline gate on the reference side.** A mutual pair is
    only read as a footnote when the reference's text is PART of its line, never the whole of
    it. A contents entry and the 「back to contents」 link at the end of a chapter point at each
    other exactly the same way, and a contents entry IS its whole line — without this gate a
    table of contents becomes a page of footnotes. This is a structural test, not a length one.

    ⚠️ INTENTIONAL — **DO NOT decide which end of a mutual pair is the reference by anything
    but reading order.** The earlier one is the reference. Both ends are inline links pointing
    at each other, so without this every note counted its own way home as a second reference
    and put a note's number on the line of prose it came from (measured: 2048 「references」 for
    1024 pairs — exactly twice what the books hold). Reading order is the premise the whole
    footnote pass already rests on: a note never comes before the text that cites it, 0
    counter-examples across the sample library.

    Then, however the note was found, WHAT ITS REFERENCE SHOWS decides how it is written. A
    note is normally numbered, and the test is the marker character set — never a length, never
    a look (see [_is_marker]):

      * a marker (`1`, `[1]`, `①`, `*1`, `（註1）`) -> the marker is the note's name. It is
        replaced where it stands: `(註[1])` in the text, `註[1]: …` at the note.
      * WORDS -> a book can hang the note on a WORD (a term in the sentence links to a page
        that explains it). Those words are the reader's text and have to stay, and the note has
        no name of its own. So it is given one, added after the words rather than replacing
        them: `<the words> (註[★1])` in the text, `註[★1]: …` at the note. 75 notes in 4 books,
        measured.

    ⚠️ INTENTIONAL — **DO NOT hand out ★ numbers per REFERENCE.** They are per NOTE, book-wide.
    One note can be pointed at by two DIFFERENTLY WORDED references: a book's note line names two
    related terms and carries an id on each, and the sentences link one term each. Both have to
    say the same number, or the second says 註[★2] with nothing anywhere that answers to it. Two
    ids inside one note element are one note, which is what [_NoteScan.note_groups] is for.
    """
    note_ids: set[str] = set()
    groups: list[list[str]] = []
    # (target key, shown text, declared, the ids it owns, is it the whole line)
    links: list[tuple[str, str, bool, list[str], bool]] = []
    for doc in docs:
        try:
            scan = _NoteScan(doc)
            scan.feed(book.read_text(doc))
            scan.close()
        except KeyError:
            continue
        note_ids |= scan.note_ids
        groups.extend(scan.note_groups)
        for key, text, declared, ids, line in scan.links:
            whole = _norm(text) == _norm(scan.lines[line]) if line < len(scan.lines) else True
            links.append((key, text, declared, ids, whole))
    # Which link carries which id — a note's way home names the reference by its id.
    owner: dict[str, int] = {}
    for i, link in enumerate(links):
        for key in link[3]:
            owner.setdefault(key, i)
    for i, (key, text, declared, ids, whole) in enumerate(links):
        if declared or key in note_ids or not text or whole:
            continue
        home = owner.get(key)
        if home is None or home <= i or links[home][0] not in ids:
            continue
        note_ids.add(key)  # a note that simply never said it was one
    shown_at: dict[str, str] = {}  # in first-appearance order, which is what ★ numbers follow
    for key, text, declared, _ids, _whole in links:
        if text and (declared or key in note_ids):
            shown_at.setdefault(key, text)
    group_of = {key: n for n, keys in enumerate(groups) for key in keys}
    labels: dict[str, str] = {}
    stars: dict[str, int] = {}
    numbered: dict[int, int] = {}  # note element -> the ★ number its first reference got
    count = 0
    for key, text in shown_at.items():
        if _is_marker(text):
            labels[key] = text
            continue
        group = group_of.get(key)
        if group is not None and group in numbered:
            stars[key] = numbered[group]  # a second reference to a note already numbered
            continue
        count += 1
        stars[key] = count
        if group is not None:
            numbered[group] = count
    return note_ids, labels, stars


class _Notes:
    """What ONE document needs to know to write this book's footnotes."""

    def __init__(self, doc: str, note_ids: set[str], labels: dict[str, str], word: str,
                 stars: dict[str, int] | None = None) -> None:
        self.doc = doc
        self._ids = note_ids
        self._labels = labels
        self._stars = stars or {}
        self.word = word

    def reference(self, href: str, declared: bool) -> str:
        """The text a reference to a note should show, or '' when this is not one."""
        key = _anchor_key(self.doc, href)
        if not declared and key not in self._ids:
            return ""
        return self._labels.get(key, "")

    def label_for(self, element_id: str) -> str:
        """The text the reference to this note showed, or ''."""
        return self._labels.get(f"{self.doc}#{element_id}", "")

    def star(self, href: str) -> int:
        """The ★ number of the note this link explains, or 0 — see [_note_index]."""
        return self._stars.get(_anchor_key(self.doc, href), 0)

    def star_for_id(self, element_id: str) -> int:
        """The ★ number of the note that lives at this id, or 0."""
        return self._stars.get(f"{self.doc}#{element_id}", 0)

    def star_label(self, number: int) -> str:
        return f"{self.word}[★{number}]"


class _BodyStyle:
    """What this book's ORDINARY paragraph looks like, measured from the book itself.

    Every question in [_sub_headings]'s fourth signal and in the caption test is asked against
    these two numbers, never against a fixed value — a book whose body text is 1.2em has no
    "1.2em heading", and a book that indents nothing cannot say anything by not indenting.
    """

    def __init__(self, size: float = 1.0, indented: bool = False) -> None:
        self.size = size
        # ⚠️ Only true when MOST of the book's paragraphs carry a text-indent from the
        # stylesheet. In a book that never declares one, "no indent" says nothing at all, so
        # the signal that depends on it is switched off rather than guessed at.
        self.indented = indented


def _body_style(book: "Epub", docs: list[str]) -> _BodyStyle:
    """Measure the book's ordinary paragraph: its font-size, and whether it is indented.

    Read book-wide, before anything is written, for the same reason [_note_index] is: one
    document can be all headings, and its own most-common size would then be a heading size.
    """
    sizes: dict[float, int] = {}
    indented = total = 0
    for doc in docs:
        try:
            html = book.read_text(doc)
        except KeyError:
            continue
        css = book.css_for(doc, html)
        parser = _BlockText()
        parser.feed(html)
        parser.close()
        for chain in parser.chains:
            if not chain:
                continue
            classes = chain[-1][1]
            size = css.run_size(classes)
            sizes[1.0 if size is None else size] = sizes.get(1.0 if size is None else size, 0) + 1
            total += 1
            if css.run_indented(classes):
                indented += 1
    if not total:
        return _BodyStyle()
    return _BodyStyle(max(sizes, key=lambda k: sizes[k]), indented * 2 > total)


_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SUBHEAD_PLAIN = 1  # a blank line above and below it
SUBHEAD_BOXED = 2  # the book drew a box: a line of `=` above and below instead
CAPTION = 3  # a picture's caption: written as 圖:[...] with one blank line either side

# What a picture caption is called, in the book's own language — same idea as [_note_word].
_CAPTION_WORDS = {"zh-hant": "圖", "zh-hans": "图", "ja": "図", "ko": "그림"}


def _caption_word(language: str) -> str:
    code = (language or "").lower().replace("_", "-")
    if code.startswith("ja"):
        return "図"
    if code.startswith("ko"):
        return "그림"
    if code.startswith("zh"):
        return "图" if any(tag in code for tag in ("hans", "-cn", "-sg", "-my")) else "圖"
    return "Fig"


def _sub_headings(
    lines: list[str],
    chain_of: list[list[tuple[str, list[str]]]],
    runs_of: list[list[tuple[str, str, list[str]]]],
    css: _Css,
    body: "_BodyStyle | None" = None,
    after_image: list[bool] | None = None,
    in_notes: list[bool] | None = None,
) -> list[int]:
    """Which lines are a sub-heading inside a chapter, and did the book box it in?

    A chapter's own title becomes a `--==# … #==--` marker, but the sub-headings under it
    had nowhere to go — they came out as ordinary indented paragraphs and read as the first
    line of the text below them. Three signals, all structural, none of them measured:

      * a heading element (`<h1>`…`<h6>`) that the chapter title did not use up, or
      * a line whose text is entirely one styled inline run that the stylesheet draws a
        border around — the way a book marks a heading without saying `<h3>`, or
      * ⚠️ **the FIRST line of the document**, when the runs that make it up account for all
        of it and the stylesheet sets any of them bigger or bolder than the body
        — one sample book's chapter opener is
        `<span class="big">〈Title〉</span><span class="mid">──subtitle</span>`, no border at
        all, and it was coming out as an indented paragraph right under the box's rule.

    ⚠️ **DO NOT drop the "first line" half of that third signal.** Bigger-or-bolder on its
    own is NOT a heading test: several books in the sample library set their classical-Chinese
    quotations in exactly the same larger bold face, and asking it of every line called
    **940 lines across 14 books** headings — classical poems, a passage of ritual text,
    92-character paragraphs of plain prose. Restricted to a spine document's first line it caught
    **137 lines across 6 books and every one of them was a heading**, because a quotation is
    never the first thing in a chapter. Widening it back needs the owner, plus numbers.

    Which shape a heading is written in follows the book: a boxed heading keeps its box
    (a line of `=` above and below), a plain one just gets air around it.

    ⚠️ A heading only becomes a sub-heading if it survives to [_paragraph_blocks], which
    runs AFTER the chapter title has been taken off the front of the section. Deciding it
    here and writing it there is deliberate — box the line first and the title match
    ("is the first line of this section the same as its label?") would be comparing the
    label against a row of `=`, and every chapter would print its title twice.
    """
    body = body or _BodyStyle()
    images = after_image or [False] * len(lines)
    noted = in_notes or [False] * len(lines)
    out: list[int] = []
    for i, (line, chain, runs) in enumerate(zip(lines, chain_of, runs_of)):
        if noted[i]:
            # ⚠️ Inside the notes area nothing is a sub-heading. Books wrap each note in a
            # heading tag (`<li><h3><a role="doc-backlink">[1]　見《…》</a></h3></li>`), and
            # taking that at face value put every note at column 0 — which in this format means
            # "sub-heading", so a whole page of notes came out in bold.
            out.append(0)
            continue
        tag, classes = chain[-1] if chain else ("", [])
        whole = [(t, c) for text, t, c in runs if text == line]
        boxed = any(
            css.framed(run_tag, run_classes) or css.run_framed(run_classes)
            for run_tag, run_classes in whole
        )
        # every class that styles this line: the block's own, plus the runs that cover it
        styling = list(classes)
        for _text, _tag, run_classes in runs:
            styling += run_classes
        size = css.run_size(styling)
        if size is None:
            size = body.size
        covered = bool(runs) and _norm("".join(text for text, _t, _c in runs)) == _norm(line)
        if tag in _HEADING_TAGS:
            out.append(SUBHEAD_BOXED if boxed or css.framed(tag, classes) else SUBHEAD_PLAIN)
        elif boxed:
            out.append(SUBHEAD_BOXED)
        elif (
            images[i]
            and size < body.size
            and css.run_has(styling, "text-align", "center")
        ):
            # The text right after a picture, set SMALLER than the body and centred: that is
            # a caption, and the picture it belongs to cannot come along (owner 2026-07-30).
            out.append(CAPTION)
        elif i == 0 and covered and any(
            css.heavier(run_classes) for _text, _tag, run_classes in runs
        ):
            out.append(SUBHEAD_PLAIN)
        elif (
            body.indented
            and covered
            and size > body.size
            and not css.run_indented(styling)
        ):
            # ⚠️ The fourth signal, and the gate matters as much as the test: **bigger than
            # this book's body AND not carrying the indent this book's body carries**. Books
            # that mark their sub-headings this way indent every ordinary paragraph in CSS
            # (`text-indent: 2em`) and leave the heading un-indented — the same statement the
            # RTB-1 format makes in its own text. It is switched off entirely in a book that
            # does not indent (`body.indented`), because there "no indent" says nothing.
            #
            # Underlined as well → the book drew a line under it, so it gets the box. Measured
            # across the library: 258 plain and 98 underlined, in 4 books, the longest 29
            # characters and every one of them a heading.
            out.append(SUBHEAD_BOXED if css.run_has(styling, "text-decoration", "underline")
                       or css.run_has(styling, "text-decoration-line", "underline")
                       else SUBHEAD_PLAIN)
        else:
            out.append(0)
    return out


# A cell's borders are the grid of a table, not a line drawn across the page.
_TABLE_TAGS = {"table", "thead", "tbody", "tr", "td", "th", "caption"}


def _border_rules(
    lines: list[str],
    anchors: dict[str, int],
    blanks: list[int],
    boxes: list[tuple[int, int, str, list[str]]],
    css: _Css,
    heads: list[int] | None = None,
) -> tuple[list[str], dict[str, int], list[int], list[int]]:
    """Draw the lines a book draws with a border instead of with `<hr>`.

    A block with a visible top border gets a rule line in front of its first line, one
    with a bottom border gets one after its last. `border:` on its own is a box, so it
    gets both.

    This pass also collapses two rules in a row into one, and it runs even when the book
    draws no borders at all: a book that puts a picture between two `<hr/>` (a real sample
    book does) loses the picture in a text file and would otherwise show the two lines
    stacked on top of each other.

    The anchor map is rebuilt as the lines shift; a stale index there would send a
    chapter's TOC entry to the wrong paragraph.
    """
    before: set[int] = set()
    after: set[int] = set()
    for first, last, tag, classes in boxes:
        if tag in _TABLE_TAGS:
            continue
        top, bottom = css.edges(tag, classes)
        if top:
            before.add(first)
        if bottom:
            after.add(last)

    kinds = heads if heads is not None else [0] * len(lines)
    out: list[str] = []
    out_blanks: list[int] = []
    out_heads: list[int] = []

    def push(text: str, blank: int, kind: int = 0) -> int:
        """Append a line, except that two rules in a row become one. The book's own
        `<hr/>` sitting right at the edge of a bordered box is the case that needs it —
        both are the same line on the page."""
        if text == HORIZONTAL_RULE and out and out[-1] == HORIZONTAL_RULE:
            out_blanks[-1] = max(out_blanks[-1], blank)
            return len(out) - 1
        out.append(text)
        out_blanks.append(blank)
        out_heads.append(kind)
        return len(out) - 1

    moved: dict[int, int] = {}
    for i, line in enumerate(lines):
        carried = blanks[i]
        if i in before:
            push(HORIZONTAL_RULE, carried)
            carried = 0
        moved[i] = push(line, carried, kinds[i])
        if i in after:
            push(HORIZONTAL_RULE, 0)

    # A drawn line is a break by itself, so it needs at most one blank line on either
    # side of it (owner 2026-07-29). Two or three there — which happens where the book
    # already left space around the block the border encloses — just pushes the line
    # adrift in the middle of a hole.
    for i, line in enumerate(out):
        if line != HORIZONTAL_RULE:
            continue
        out_blanks[i] = min(out_blanks[i], 1)
        if i + 1 < len(out):
            out_blanks[i + 1] = min(out_blanks[i + 1], 1)
    return out, {k: moved.get(v, v) for k, v in anchors.items()}, out_blanks, out_heads


# ------------------------------------------------------------- HTML extraction


class _BlockText(HTMLParser):
    """XHTML -> one line per block element, plus where each id anchor lands.

    A book's paragraph structure lives in its block elements, so extracting text
    per block gives exactly "one line = one paragraph". Inline tags no longer
    chop a sentence in half (the old converter's `get_text(separator='\\n')`
    broke lines at every `<span>`), and `<rt>` ruby annotations are dropped
    rather than inlined into the middle of a word.
    """

    BLOCK = {
        "address", "article", "aside", "blockquote", "body", "caption", "center",
        "dd", "div", "dl", "dt", "figcaption", "figure", "footer", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "nav",
        "ol", "p", "pre", "section", "table", "tbody", "td", "th", "thead", "tr",
        "ul",
    }
    SKIP = {"head", "script", "style", "rt", "rp"}
    # An element with no end tag: pushing it onto a stack would leave the stack one deep
    # for the rest of the document.
    VOID = {"br", "img", "wbr", "area", "base", "col", "embed", "input", "link", "meta",
            "param", "source", "track"}

    def __init__(self, notes: "_Notes | None" = None) -> None:
        super().__init__(convert_charrefs=True)
        self.notes = notes
        # Open note elements, as len(_open) at which each opened — so its end tag is found
        # without threading another field through the block stack.
        self._note_depth: list[int] = []
        # The note being written: (what its reference showed, the label to print). Filled
        # when the note opens, or later from an id inside it (some books put the id on the
        # back-link, not on the note element).
        self._note: tuple[str, str] | None = None
        self._note_pending = False  # the note's first line has not been labelled yet
        # after_image[i] = an <img>/<image> was seen since the previous line. A book's picture
        # caption is the text right after the picture, and the picture cannot come along.
        self.after_image: list[bool] = []
        self._saw_image = False
        # Open notes-AREA containers, as len(_open) at which each opened. Inside one, every
        # block starts a new note (books mark the area and not the notes), and a heading tag is
        # list furniture rather than a chapter sub-heading.
        self._area_depth: list[int] = []
        self.in_notes: list[bool] = []
        # (first chunk, last chunk) of each link inside a note that points back into the text.
        # Dropped at flush, but ONLY when the note has text outside them — see [_close_link].
        self._back: list[tuple[int, int]] = []
        # Which lines open a note. A book introduces its notes with a rule (`<hr>`) and
        # sometimes leaves no air above it — see the note branch in [_extract].
        self.note_lines: set[int] = set()
        self.lines: list[str] = []
        self.anchors: dict[str, int] = {}
        # blanks[i] = how many whitespace-only blocks the source had immediately
        # before lines[i]. A book uses those for deliberate breathing space (before a
        # quotation, around a sub-heading), and dropping them flattens the page.
        self.blanks: list[int] = []
        # chains[i] = the open block elements around lines[i], outermost first, each as
        # (tag, classes). That is what the stylesheet is asked about — the innermost
        # entry is the paragraph itself, the rest are where an inherited font comes from.
        self.chains: list[list[tuple[str, list[str]]]] = []
        # owners[i] = which block element lines[i] came out of. Two lines can share one:
        # a poem is often a single <p> with <br/> between its verses, and there is no
        # margin *inside* an element — see [_extra_blanks].
        self.owners: list[int] = []
        self._block_seq = 0
        # every block element that produced at least one line: (first line, last line,
        # tag, classes) — what [_border_rules] needs to know where a box begins and ends.
        self.boxes: list[tuple[int, int, str, list[str]]] = []
        # runs[i] = every INLINE element that closed inside lines[i], as (text, tag, classes),
        # in closing order. A book very often marks a sub-heading with a <span> inside an
        # ordinary <p> rather than with <h3>. Two questions are asked of this list, and both
        # need the whole line to be accounted for — a styled run in mid-sentence is emphasis,
        # not a heading: "is there a run whose text IS the line" and "do the runs together
        # cover the line" (see [_sub_headings]).
        self.runs: list[list[tuple[str, str, list[str]]]] = []
        # open inline elements that carry a class: (how much of _buf preceded it, tag,
        # classes). Cleared at every line break — an offset into a buffer that has been
        # flushed means nothing.
        self._runs: list[tuple[int, str, list[str]]] = []
        self._done: list[tuple[str, str, list[str]]] = []  # (text, tag, classes), this line
        # Did THIS line get a note marker from us? Only those get their spacing normalised —
        # a book printing 「(註[2])」 as its own text keeps whatever spacing the author chose.
        self._wrote_mark = False
        self._buf: list[str] = []
        self._skip = 0
        # one entry per open <a>: (how much of _buf was already there, its address or "",
        # its footnote role: "" none, "back" a note's way home, else the label to print)
        self._links: list[tuple[int, str, str]] = []
        self._pending: list[str] = []
        self._pending_blanks = 0
        # one entry per open block element: (len(lines) when it opened, blocks closed
        # inside it, its tag, its classes, its serial number). A block that closed with
        # no line of its own AND no block children was an empty paragraph; requiring no
        # children is what stops a wrapper <div> from being counted again around the
        # <p> it holds.
        self._open: list[tuple[int, int, str, list[str], int]] = []

    # -- HTMLParser hooks
    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in self.SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in self.BLOCK or tag == "br":
            self._flush()  # flush BEFORE recording ids, so an id maps to what follows
        values = dict(attrs)
        # `hr` is void: it never gets an end tag, so pushing it would leave the stack
        # one deep for the rest of the document.
        if tag in self.BLOCK and tag != "hr":
            self._block_seq += 1
            self._open.append((len(self.lines), 0, tag, (values.get("class") or "").split(), self._block_seq))
            self._open_note(values)
            if self.notes is not None and _is_note_area(values):
                self._area_depth.append(len(self._open))
        if tag in ("img", "image"):
            self._saw_image = True
        if tag == "hr":
            self._buf.append(HORIZONTAL_RULE)
            self._flush()
        if (
            self.notes is not None
            and not self._note_depth
            and values.get("id")
            and self.notes.label_for(values["id"])
        ):
            # An id that the text points at as a note IS one note, even when nothing marks the
            # element carrying it. Books put that id in three places and all three land here:
            # on the note's block (a notes list's `<li>`), on the link back into the text
            # inside it, or on a `<span>` around the number the note prints.
            #
            # ⚠️ It has to be the ID that starts the note, not merely 「a block inside the notes
            # area」. A wrapping `<ol>` has no id, and letting it open the note made ONE note
            # out of the whole list — the first `<li>` took the label and every other note came
            # out unlabelled.
            self._note_depth = [len(self._open)]
            self._note, self._note_pending = None, True
            self._name_note(values["id"])
        elif self._note is None and self._note_depth and values.get("id"):
            self._name_note(values["id"])  # some books put the id on the back-link
        if tag == "a":
            href = (values.get("href") or "").strip()
            marks = " ".join((values.get("epub:type", ""), values.get("role", ""),
                              values.get("rel", ""))).lower()
            role = ""
            if href and not EXTERNAL_LINK.match(href) and self.notes is not None:
                if self._note_depth:
                    # A link inside a note that points back into the text is the reader's
                    # way home; in a .txt it is furniture with nothing to point at, and its
                    # text (`↺`, `1.`, `註1`) is not part of the note.
                    role = "back"
                else:
                    shown = self.notes.reference(href, "noteref" in marks or "footnote" in marks)
                    star = 0 if shown else self.notes.star(href)
                    if shown:
                        role = _note_label(self.notes.word, shown)
                    elif star:
                        # Words that point at an explanation. The words are the reader's
                        # text, so the marker is ADDED after them rather than replacing
                        # them — see [_note_index].
                        role = f"after:{self.notes.star_label(star)}"
            self._links.append((len(self._buf), _clean_url(href) if EXTERNAL_LINK.match(href) else "", role))
        if tag not in self.BLOCK and tag not in self.VOID and values.get("class"):
            self._runs.append((len(self._buf), tag, values["class"].split()))
        for key in ("id", "name"):
            value = values.get(key)
            if value:
                self._pending.append(value)

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag in self.SKIP:
            return  # self-closing <script/> etc. has no content to skip
        self.handle_starttag(tag, attrs)
        if tag in self.BLOCK and tag != "hr" and self._open:
            self._open.pop()  # a self-closed block has no content; keep the stack balanced
            self._close_note()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "a" and self._links:
            self._close_link(*self._links.pop())
        for i in range(len(self._runs) - 1, -1, -1):
            if self._runs[i][1] == tag:
                start, run_tag, classes = self._runs[i]
                # Anything still open inside it was never closed; it ends here too.
                self._runs = self._runs[:i]
                text = _collapse("".join(self._buf[start:]))
                if text:
                    self._done.append((text, run_tag, classes))
                break
        if tag in self.BLOCK and tag != "hr":
            self._flush()
            if self._open:
                opened_at, children, tag_, classes_, _uid = self._open.pop()
                if len(self.lines) > opened_at:
                    self.boxes.append((opened_at, len(self.lines) - 1, tag_, classes_))
                if self._open:  # tell the parent it had a block child
                    at, kids, otag, ocls, ouid = self._open[-1]
                    self._open[-1] = (at, kids + 1, otag, ocls, ouid)
                if children == 0 and len(self.lines) == opened_at:
                    self._pending_blanks += 1
            self._close_note()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.append(data)

    # -- internals
    def _open_note(self, values: dict[str, str]) -> None:
        """Note whether this block element is a footnote, and what to label it with."""
        if self.notes is None:
            return
        if not _is_note_element(values):
            return
        self._note_depth.append(len(self._open))
        self._note_pending = True
        if values.get("id"):
            self._name_note(values["id"])

    def _name_note(self, element_id: str) -> None:
        shown = self.notes.label_for(element_id) if self.notes else ""
        if shown:
            self._note = (shown, _note_label(self.notes.word, shown))  # type: ignore[union-attr]

    def _close_note(self) -> None:
        while self._note_depth and self._note_depth[-1] > len(self._open):
            self._note_depth.pop()
            if not self._note_depth:
                self._note, self._note_pending = None, False
        while self._area_depth and self._area_depth[-1] > len(self._open):
            self._area_depth.pop()

    def _close_link(self, start: int, href: str, role: str = "") -> None:
        """Write an outbound link's address into the text (owner 2026-07-29).

        A .txt cannot be clicked, so an address that only exists in an `href` is simply
        lost — and these are the addresses a reader actually wants (an author's Facebook
        page, a source a footnote cites). The address goes right after the words it
        belongs to, wrapped in angle brackets:

            ＦＢ：the illustrator <https://www.facebook.com/example/>

        The brackets are the plain-text convention for exactly this, and they are what
        makes it machine-readable: a URL runs right up against the next character, so
        「…/?hl=zh-tw，接著」 gives a program no way to see where the address ended.

        Two shapes need no words in front. A link whose content is a picture (a Facebook
        icon) has no text of its own, and one whose text already IS its address would
        otherwise say it twice — in both cases the address alone stands where the link was,
        which for the usual 「a line of text, then the icon」 layout puts it on its own line.

        A footnote link is rewritten instead (owner 2026-07-30, `role`): a reference in the
        text becomes `(註[2])` where it showed a bare `2`, and a note's way back into the
        text disappears — in a .txt it has nothing to point at, and its text (`↺`, `1.`) is
        the reader's furniture, not the note.
        """
        start = min(start, len(self._buf))
        if role.startswith("after:"):
            self._wrote_mark = True
            self._buf.append(f"({role[len("after:"):]})")
            return
        if role == "back":
            # ⚠️ NOT deleted here. Some books put the whole note INSIDE the link that points
            # back to the text — `<p epub:type="footnote"><a href="#ref">1　編註：…</a></p>` —
            # and deleting the link then deleted the note. The decision needs the rest of the
            # block, so it is deferred to [_flush]: a back-link is furniture only when the note
            # has other text outside it. 8 notes were lost to this before it was caught.
            self._back.append((start, len(self._buf)))
            return
        if role:
            self._wrote_mark = True
            self._buf[start:] = [f"({role})"]
            return
        if not href:
            return
        text = _collapse("".join(self._buf[start:]))
        if not text or _same_target(text, href):
            self._buf[start:] = [f"<{href}>"]
        else:
            self._buf.append(f" <{href}>")

    def _flush(self) -> None:
        # A link back into the text is the reader's way home and has nothing to point at in a
        # .txt — but only when the note says something else too. When the note's whole content
        # is inside that link, the link IS the note (see [_close_link]).
        if self._back:
            keep = [chunk for i, chunk in enumerate(self._buf)
                    if not any(a <= i < b for a, b in self._back)]
            if _collapse("".join(keep)):
                self._buf = keep
            self._back = []
        text = _collapse("".join(self._buf))
        runs, self._buf, self._done, self._runs = self._done, [], [], []
        if not text:
            return  # keep pending ids: they belong to the next line with content
        # A publisher often puts a text link and a clickable icon side by side, both
        # pointing at the same page. The icon's address would then repeat the line above
        # it verbatim, so drop it — the address is not lost, it is already there.
        if LONE_LINK.match(text) and self.lines and text in self.lines[-1]:
            return
        if self._note_pending and self._note:
            shown, label = self._note
            # 「2 參見《某書》」 -> 「註[2]: 參見《某書》」. The number the note
            # prints itself is plain text, not markup, so it can only be taken off by
            # comparing it against the value we already know — never by pattern.
            if text.startswith(shown):
                text = text[len(shown):]
            # The marker this label replaces took its own separator with it. A real book
            # writes 「註1：見《…》…」 with `註1` inside the back-link and the colon as plain text,
            # so dropping only the link left 「註[1]: ：見《…》」. ONE character, from a
            # closed list, and only ever immediately after a marker that was just removed.
            text = text.lstrip()
            if text[:1] in NOTE_SEPARATORS:
                text = text[1:].lstrip()
            text = f"{label}: {text}" if text else label
            self._note_pending = False
            self.note_lines.add(len(self.lines))
        # One space each side of every marker this line carries (owner 2026-07-31): the two
        # ways of writing one land differently otherwise — 「綠茶(註[4])必學」 against
        # 「香菸 (註[★1])味」 — and a marker jammed against the words reads as part of them.
        if self._wrote_mark:
            text = _space_note_marks(text)
            self._wrote_mark = False
        self.lines.append(text)
        self.blanks.append(self._pending_blanks)
        self.chains.append([(tag, classes) for _at, _kids, tag, classes, _uid in self._open])
        self.owners.append(self._open[-1][4] if self._open else 0)
        self.runs.append(runs)
        self.in_notes.append(bool(self._area_depth or self._note_depth))
        self.after_image.append(self._saw_image)
        self._saw_image = False
        self._pending_blanks = 0
        for anchor in self._pending:
            self.anchors.setdefault(anchor, len(self.lines) - 1)
        self._pending = []

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def _star_targets(
    lines: list[str], anchors: dict[str, int], blanks: list[int], heads: list[int],
    notes: "_Notes | None",
) -> tuple[list[str], dict[str, int], list[int], list[int]]:
    """Write the `註[★N]: …` line that the ★ references in the text point at.

    A ★ note has no number of its own anywhere — the book pointed words at an explanation
    (see [_note_index]) — so both ends of the pair are written here rather than read.

    The explanation is usually a sub-heading followed by its paragraphs. That heading keeps
    being a heading, and the note's line goes in FRONT of it, repeating its words (owner
    2026-07-30). Prefixing the heading itself would have cost the book a heading; a target
    that is NOT a heading (a one-line explanation) is prefixed in place, so its words are
    not said twice.
    """
    if notes is None:
        return lines, anchors, blanks, heads
    at: dict[int, int] = {}
    for element_id, index in anchors.items():
        number = notes.star_for_id(element_id)
        # A rule is not a line of text and cannot be quoted into a note's line.
        if number and index < len(lines) and lines[index] != HORIZONTAL_RULE:
            at.setdefault(index, number)
    if not at:
        return lines, anchors, blanks, heads
    out_lines: list[str] = []
    out_blanks: list[int] = []
    out_heads: list[int] = []
    moved: dict[int, int] = {}
    for i, line in enumerate(lines):
        number = at.get(i)
        if number and heads[i]:
            moved[i] = len(out_lines)  # the id points at the NOTE, which is what it is
            out_lines.append(f"{notes.star_label(number)}: {line}")
            out_blanks.append(blanks[i])
            out_heads.append(0)
            out_lines.append(line)
            out_blanks.append(0)
            out_heads.append(heads[i])
            continue
        moved[i] = len(out_lines)
        out_lines.append(f"{notes.star_label(number)}: {line}" if number else line)
        out_blanks.append(blanks[i])
        out_heads.append(heads[i])
    return (out_lines, {name: moved.get(at_, at_) for name, at_ in anchors.items()},
            out_blanks, out_heads)


def _extract(
    html: str, css: "_Css | None" = None, notes: "_Notes | None" = None,
    body: "_BodyStyle | None" = None, caption_word: str = "圖",
) -> tuple[list[str], dict[str, int], list[int], list[int]]:
    """(paragraphs, id anchor -> paragraph index, blank lines before each, sub-heading kinds).

    With a stylesheet, the blank count also picks up the space the book asked for in CSS
    rather than with an empty paragraph (see [_extra_blanks]). A position that already
    has a blank line keeps the one it has — the two are the same statement made twice,
    not two separate gaps.
    """
    parser = _BlockText(notes)
    parser.feed(html)
    parser.close()
    blanks = parser.blanks
    # A heading element is a heading with or without a stylesheet; only the box needs CSS.
    heads = _sub_headings(parser.lines, parser.chains, parser.runs, css or _Css(),
                          body, parser.after_image, parser.in_notes)
    # A caption is written 圖:[…] so a reader — and a person in Notepad — can tell it from the
    # prose around it; the picture it described is not in a text file (owner 2026-07-30).
    for i, kind in enumerate(heads):
        if kind == CAPTION:
            parser.lines[i] = f"{caption_word}:[{parser.lines[i]}]"
    # A book introduces its notes with a rule of its own (`<hr>`), and some leave no air
    # above it — the last line of the chapter then sits right on top of the line
    # (owner 2026-07-30). One blank line is ENSURED rather than added: three of the four
    # books with notes already have one from their own markup, and adding a second would
    # push the rule adrift. The rule is found structurally — the line right before a note.
    for i in parser.note_lines:
        if i > 0 and parser.lines[i - 1] == HORIZONTAL_RULE:
            blanks[i - 1] = max(blanks[i - 1], 1)
    if css is None:
        return _star_targets(parser.lines, parser.anchors, blanks, heads, notes)
    extra = _extra_blanks(parser.chains, parser.owners, css)
    blanks = [max(had, more) for had, more in zip(blanks, extra)]
    return _star_targets(
        *_border_rules(parser.lines, parser.anchors, blanks, parser.boxes, css, heads), notes)


class _NavParser(HTMLParser):
    """EPUB3 nav document -> [(depth, href, label)] for the toc nav."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.navs: list[tuple[str, list[tuple[int, str, str]]]] = []
        self._nav_type: str | None = None
        self._entries: list[tuple[int, str, str]] = []
        self._depth = 0
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        values = dict(attrs)
        if tag == "nav":
            self._nav_type = (values.get("epub:type") or values.get("type") or "").strip()
            self._entries = []
            self._depth = 0
        elif tag == "ol" and self._nav_type is not None:
            self._depth += 1
        elif tag == "a" and self._nav_type is not None:
            self._href = values.get("href") or ""
            self._label = []

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            label = _collapse("".join(self._label))
            if label:
                self._entries.append((max(1, self._depth), self._href, label))
            self._href = None
        elif tag == "ol" and self._nav_type is not None:
            self._depth = max(0, self._depth - 1)
        elif tag == "nav" and self._nav_type is not None:
            self.navs.append((self._nav_type, self._entries))
            self._nav_type = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._label.append(data)


def _nav_entries(html: str) -> list[tuple[int, str, str]]:
    parser = _NavParser()
    parser.feed(html)
    parser.close()
    for nav_type, entries in parser.navs:
        if "toc" in nav_type.lower() and entries:
            return entries
    for _, entries in parser.navs:
        if entries:
            return entries
    return []


def _ncx_entries(xml: str) -> list[tuple[int, str, str]]:
    """EPUB2 NCX fallback: nested navPoints carry the same tree."""
    try:
        root = _parse_xml(xml.encode('utf-8'))
    except (ElementTree.ParseError, ValueError):
        return []
    out: list[tuple[int, str, str]] = []

    def walk(node, depth: int) -> None:  # type: ignore[no-untyped-def]
        for child in node:
            if _local(child.tag) != "navpoint":
                continue
            label = ""
            href = ""
            for part in child:
                name = _local(part.tag)
                if name == "navlabel":
                    label = _collapse("".join(part.itertext()))
                elif name == "content":
                    href = part.get("src") or ""
            if label and href:
                out.append((depth, href, label))
            walk(child, depth + 1)

    for node in root:
        if _local(node.tag) == "navmap":
            walk(node, 1)
    return out


# ------------------------------------------------------------------ EPUB model


class Epub:
    """Just enough of the EPUB package to convert it: metadata, spine, TOC."""

    def __init__(self, path: Path) -> None:
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())
        opf_name = self._rootfile()
        self.base = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
        opf_bytes = self._read_bytes(opf_name)
        opf = _parse_xml(opf_bytes)

        self.title = ""
        self.authors: list[str] = []
        self.publisher = ""
        self.date = ""
        self.language = ""
        self.series = ""
        self.series_index = ""
        self.items: dict[str, tuple[str, str, str]] = {}  # id -> (href, media, props)
        self.spine: list[str] = []  # item ids, reading order
        self.nav_id: str | None = None
        self.ncx_id: str | None = None
        self._cover_id: str | None = None  # EPUB2 <meta name="cover" content="id">
        # One stylesheet serves the whole book in most EPUBs; read each file once.
        self._css_cache: dict[str, str] = {}
        # A fixed-layout (pre-paginated) book judges "is it a comic" by a stricter
        # rule than a reflowable one — see image_book_verdict.
        self.pre_paginated = b"pre-paginated" in opf_bytes.lower()

        for section in opf:
            kind = _local(section.tag)
            if kind == "metadata":
                self._read_metadata(section)
            elif kind == "manifest":
                for item in section:
                    if _local(item.tag) != "item":
                        continue
                    item_id = item.get("id") or ""
                    href = item.get("href") or ""
                    media = (item.get("media-type") or "").lower()
                    props = (item.get("properties") or "").lower()
                    if not item_id or not href:
                        continue
                    self.items[item_id] = (href, media, props)
                    if "nav" in props.split():
                        self.nav_id = item_id
                    if media == "application/x-dtbncx+xml":
                        self.ncx_id = item_id
            elif kind == "spine":
                toc_attr = section.get("toc")
                if toc_attr:
                    self.ncx_id = self.ncx_id or toc_attr
                for ref in section:
                    if _local(ref.tag) != "itemref":
                        continue
                    idref = ref.get("idref")
                    if idref:
                        self.spine.append(idref)

        self.cover_image_name = self._find_cover()

    def _find_cover(self) -> str | None:
        """The cover image, by two rules in this order:

        1. EPUB3: the manifest item carrying `properties="cover-image"`.
        2. EPUB2: `<meta name="cover" content="itemid">`. This one is NOT in the
           OPF 2.0.1 specification, but it is the near-universal de-facto
           convention — essentially every EPUB2 file uses it, as do many EPUB3
           files that never adopted the cover-image property. Ignoring it would
           strip real books of their cover, so compatibility wins here.

        A declaration pointing at a file the zip does not hold counts as no cover.
        """
        for href, _media, props in self.items.values():
            if "cover-image" in props.split():
                name = _zip_path(self.base, urldefrag(href)[0])
                if self._resolve(name) in self.names:
                    return name
        item = self.items.get(self._cover_id or "")
        if item and item[1].startswith("image/"):
            name = _zip_path(self.base, urldefrag(item[0])[0])
            if self._resolve(name) in self.names:
                return name
        return None

    # -- reading
    def _rootfile(self) -> str:
        root = _parse_xml(self._read_bytes("META-INF/container.xml"))
        for rootfiles in root:
            for rootfile in rootfiles:
                full = rootfile.get("full-path")
                if full:
                    return full
        raise ValueError("container.xml has no rootfile")

    def _resolve(self, name: str) -> str:
        if name not in self.names:  # some EPUBs mix separators or percent-encode
            alt = unquote(name)
            if alt in self.names:
                return alt
        return name

    def _read_bytes(self, name: str) -> bytes:
        return self.zip.read(self._resolve(name))

    def entry_size(self, name: str) -> int:
        """Uncompressed size straight from the zip directory — nothing is read or
        decompressed, so it is free to ask about every page in the book."""
        try:
            return self.zip.getinfo(self._resolve(name)).file_size
        except KeyError:
            return 0

    def read_text(self, name: str) -> str:
        raw = self._read_bytes(name)
        for encoding in ("utf-8-sig", "utf-8", "utf-16"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def css_for(self, doc: str, html: str) -> _Css:
        """The stylesheet this document is read under: every `<link>` it names, then its
        own `<style>` blocks (later wins, which is what a browser does too).

        A missing or unreadable stylesheet is simply skipped — the questions it would
        have answered come back "not declared", and nothing is added to the output."""
        css = _Css()
        base = posixpath.dirname(doc)
        for m in re.finditer(r"<link\b[^>]*>", html, re.IGNORECASE):
            tag = m.group(0)
            if "stylesheet" not in tag.lower() and "text/css" not in tag.lower():
                continue
            href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not href:
                continue
            name = _zip_path(base + "/" if base else "", href.group(1))
            if name in self._css_cache:
                css.add(self._css_cache[name])
                continue
            try:
                text = self.read_text(name)
            except KeyError:
                text = ""
            self._css_cache[name] = text
            css.add(text)
        for block in re.findall(r"<style[^>]*>(.*?)</style>", html, re.IGNORECASE | re.S):
            css.add(block)
        return css

    def _read_metadata(self, metadata) -> None:  # type: ignore[no-untyped-def]
        metas: list[tuple[str, dict[str, str]]] = []
        for node in metadata:
            name = _local(node.tag)
            value = _collapse("".join(node.itertext()))
            if name == "title" and not self.title:
                self.title = value
            elif name == "creator" and value:
                self.authors.append(value)
            elif name == "publisher" and not self.publisher:
                self.publisher = value
            elif name == "date" and not self.date:
                self.date = value
            elif name == "language" and not self.language:
                self.language = value
            elif name == "meta":
                attrs = {k.lower(): v for k, v in node.attrib.items()}
                if (attrs.get("name") or "").lower() == "cover" and attrs.get("content"):
                    self._cover_id = attrs["content"]
                metas.append((value, attrs))

        # Series: the EPUB3 standard form only — belongs-to-collection whose
        # collection-type refine says "series" (a "set" is not a reading series).
        refines: dict[str, dict[str, str]] = {}
        for value, attrs in metas:
            target = (attrs.get("refines") or "").lstrip("#")
            prop = attrs.get("property") or ""
            if target and prop:
                refines.setdefault(target, {})[prop] = value
        for value, attrs in metas:
            if (attrs.get("property") or "") != "belongs-to-collection":
                continue
            refine = refines.get(attrs.get("id") or "", {})
            kind = refine.get("collection-type")
            if kind not in (None, "series"):
                continue
            if value:
                self.series = value
                self.series_index = refine.get("group-position", "")
                break

    # -- structure
    def item_path(self, item_id: str) -> str:
        href, _, _ = self.items[item_id]
        return _zip_path(self.base, urldefrag(href)[0])

    def toc(self) -> list[tuple[int, str, str, str]]:
        """[(depth, zip path, fragment, label)] in TOC order."""
        entries: list[tuple[int, str, str]] = []
        if self.nav_id and self.nav_id in self.items:
            nav_path = self.item_path(self.nav_id)
            nav_dir = nav_path.rsplit("/", 1)[0] + "/" if "/" in nav_path else ""
            raw = _nav_entries(self.read_text(nav_path))
            entries = [(depth, _rebase(nav_dir, href), label) for depth, href, label in raw]
        if not entries and self.ncx_id and self.ncx_id in self.items:
            ncx_path = self.item_path(self.ncx_id)
            ncx_dir = ncx_path.rsplit("/", 1)[0] + "/" if "/" in ncx_path else ""
            raw = _ncx_entries(self.read_text(ncx_path))
            entries = [(depth, _rebase(ncx_dir, href), label) for depth, href, label in raw]
        out: list[tuple[int, str, str, str]] = []
        for depth, href, label in entries:
            path, fragment = urldefrag(href)
            out.append((depth, path, fragment, label))
        return out


def _rebase(directory: str, href: str) -> str:
    """A nav/NCX href is relative to the nav document, not to the OPF."""
    path, fragment = urldefrag(href)
    if not path:
        return href
    resolved = _zip_path(directory, path)
    return f"{resolved}#{fragment}" if fragment else resolved


# -------------------------------------------------------------------- emitting


# ------------------------------------------------------------ the cover trailer

# The cover rides at the very END of the file, fenced by its own marker. The fence
# is `--==[ … ]==--`, NOT the chapter fence `--==# … #==--`, so no reader (and no
# line of this script) can mistake one for the other; a reader that knows nothing
# about it just shows the block as text, which is the accepted trade (owner
# 2026-07-29). The declaration up in the header says whether it is there at all,
# so a parser never has to scan to the end of a book to find out.
COVER_OPEN = "--==[ Cover ]==--"
COVER_CLOSE = "--==[ /Cover ]==--"
COVER_MAX = (200, 300)  # the picture is fitted INSIDE this box; the ratio is kept
COVER_QUALITY = 80
BASE64_WIDTH = 76  # the usual MIME width — one screen, and it re-joins into one line


def pillow_available() -> bool:
    """Whether covers can be embedded at all. Asked once by each front end so that a
    machine without Pillow says so, instead of quietly writing `Cover: False` forever."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


def cover_jpeg_base64(book: Epub) -> str:
    """The book's cover as a JPEG that fits in 200x300, base64'd. "" when there is none.

    This is the one thing in the script that wants a package beyond the standard
    library (Pillow), because the standard library has no image codec. The import is
    deliberately made here and not at the top: without Pillow every book still
    converts exactly as before and simply declares `Cover: False`.
    """
    if not book.cover_image_name:
        return ""
    try:
        from PIL import Image
    except ImportError:
        return ""
    try:
        with Image.open(io.BytesIO(book._read_bytes(book.cover_image_name))) as source:
            picture = source.convert("RGB")  # JPEG carries neither alpha nor a palette
        picture.thumbnail(COVER_MAX)  # fits the box, keeps the aspect ratio, never enlarges
        out = io.BytesIO()
        picture.save(out, format="JPEG", quality=COVER_QUALITY, optimize=True)
    except Exception:  # noqa: BLE001 - a cover we cannot read is simply no cover
        return ""
    return base64.b64encode(out.getvalue()).decode("ascii")


def cover_block(data: str) -> str:
    lines = [data[at:at + BASE64_WIDTH] for at in range(0, len(data), BASE64_WIDTH)]
    return "\n".join([COVER_OPEN, *lines, COVER_CLOSE])


def _header_lines(book: Epub, fallback_title: str, guessed_date: str, has_cover: bool) -> list[str]:
    title = book.title or fallback_title
    lines = [FORMAT_BANNER, f"Title: {title}"]
    for author in book.authors:
        lines.append(f"Author: {author}")
    if book.publisher:
        lines.append(f"Publisher: {book.publisher}")
    date = book.date or guessed_date
    if date:
        lines.append(f"Date: {date}")
    if book.language:
        lines.append(f"Language: {book.language}")
    if book.series:
        lines.append(f"Series: {book.series}")
    if book.series_index:
        lines.append(f"Series Index: {book.series_index}")
    # Always written, both ways round: it answers "is there a cover at the end?"
    # without reading the rest of the file.
    lines.append(f"Cover: {'True' if has_cover else 'False'}")
    return lines


DATE_HINT = re.compile(r"(1[6-9]\d{2}|20\d{2})")


def _guess_date(lines: list[str]) -> str:
    """Some publishers leave dc:date empty but print the year on the title page."""
    for line in lines[:8]:
        if len(line) <= 24 and DATE_HINT.search(line):
            return line
    return ""


def _looks_like_title_page(lines: list[str], book: Epub) -> bool:
    """A title page repeats what the header already carries — drop it instead of
    printing the same four lines twice."""
    if not lines or len(lines) > 6:
        return False
    known = {_norm(book.title)} | {_norm(a) for a in book.authors}
    if book.publisher:
        known.add(_norm(book.publisher))
    first = _norm(lines[0])
    if first not in known:
        return False
    return all(_norm(line) in known or DATE_HINT.search(line) for line in lines)


def _is_cjk(language: str) -> bool:
    """Chinese or Japanese — the scripts whose paragraphs are marked by an indent."""
    code = (language or "").lower()
    return code.startswith("zh") or code.startswith("ja")


CONTENTS_PAGE_MIN_HITS = 3
CONTENTS_PAGE_PERCENT = 70


def _is_contents_page(lines: list[str], labels: set[str]) -> bool:
    """Is this spine document just the book's own contents list?

    Plenty of books carry one that their own TOC does not point at, so it arrives as
    untitled body text and the file ends up stating the same list twice — once as
    prose, once as the Contents section written below. It is recognised by content
    rather than by position: nearly every line is, exactly, one of the book's own TOC
    labels. Prose cannot trip this, because the test is whole-line equality against a
    chapter title, and a real page of text matches none of them.
    """
    if not labels:
        return False
    # Such a page usually opens with its own heading ("目錄"), which is never one of the
    # TOC labels and so would count against the page for no good reason.
    if lines and TOC_LABEL.match(lines[0]):
        lines = lines[1:]
    if len(lines) < CONTENTS_PAGE_MIN_HITS:
        return False
    hits = sum(1 for line in lines if _norm(line) in labels)
    return hits >= CONTENTS_PAGE_MIN_HITS and hits * 100 >= len(lines) * CONTENTS_PAGE_PERCENT


def _contents_word(language: str) -> str:
    """The word for a contents list, in the book's own language.

    Only words a reader recognises as a contents heading are used, so the section is
    always skipped rather than read as a chapter (see TOC_LABEL, and README.md).
    """
    return "目次" if _is_cjk(language) else "Contents"


# Two ideographic spaces — how Chinese and Japanese typesetting opens a paragraph.
# The source EPUBs carry them in the text itself (their CSS is usually `p { margin: 0 }`),
# and _collapse() strips them along with the rest of the leading whitespace, so they are
# put back here rather than invented.
PARAGRAPH_INDENT = "　　"

# The same indent for a Latin-script book (owner 2026-07-29). Every book indents its
# first line now — a paragraph break is a line break in this format, so the indent is
# what shows where a paragraph starts, in English no less than in Chinese. Four spaces
# rather than two ideographic ones: one U+3000 is about two Latin characters wide, so
# this is the same visual width, it keeps an English file plain ASCII, and it matches
# the `text-indent: 2em` a reader draws.
LATIN_INDENT = "    "


def paragraph_indent(language: str) -> str:
    """The first-line indent for a book written in this language."""
    return PARAGRAPH_INDENT if _is_cjk(language) else LATIN_INDENT


def _body_line(text: str, indent: str) -> str:
    """One body paragraph, ready to be written.

    Every paragraph opens with an indent — that is what marks a paragraph in Notepad and
    in the TXT readers that key off it, and this format spends the blank line on the
    book's own spacing instead. A reader that understands the format strips the leading
    spaces again before applying its own text-indent, so the indent changes nothing about
    how the file parses.

    The indent also subsumes the escape rule: a paragraph that happens to look like a
    chapter fence is only a fence at column 0, and an indented line no longer starts
    there. The un-indented branch is belt and braces — every language gets an indent now
    (see paragraph_indent), so nothing in this program reaches it.
    """
    if indent:
        return indent + text
    return " " + text if _looks_like_mark(text) else text


def convert(path: Path, with_cover: bool = True) -> tuple[str, str]:
    """Return (book title, the whole .txt)."""
    book = Epub(path)
    toc = book.toc()
    toc_labels = {_norm(label) for _depth, _doc, _fragment, label in toc}
    indent = paragraph_indent(book.language)

    # nav entries grouped by the document they point into.
    per_doc: dict[str, list[tuple[int, str, str]]] = {}
    for depth, doc, fragment, label in toc:
        per_doc.setdefault(doc, []).append((depth, fragment, label))

    nav_path = book.item_path(book.nav_id) if book.nav_id and book.nav_id in book.items else None
    # Footnotes are indexed across the WHOLE book before a word of it is written: a note and
    # the reference that names it are often in different documents (see [_note_index]).
    content_docs = [
        book.item_path(i) for i in book.spine
        if i in book.items and "html" in (book.items[i][1] or "html")
    ]
    note_ids, note_labels, note_stars = _note_index(book, content_docs)
    note_word = _note_word(book.language)
    # The book's ordinary paragraph, measured book-wide (see [_body_style]).
    body_style = _body_style(book, content_docs)
    caption_word = _caption_word(book.language)
    body: list[str] = []
    emitted: list[tuple[int, str]] = []  # (depth, label) of the sections actually written
    guessed_date = ""
    seen: set[str] = set()
    # TOC entries waiting for a page to land on — see the "no text at all" branch below.
    carried: list[tuple[int, str, str]] = []
    # Did the last thing written end on a heading or a caption? See [_paragraph_blocks].
    trailing_head = False

    for item_id in book.spine:
        if item_id not in book.items:
            continue
        href, media, _ = book.items[item_id]
        if media and "html" not in media:
            continue
        doc = book.item_path(item_id)
        if doc == nav_path or doc in seen:
            continue  # our own Contents replaces the nav document
        seen.add(doc)
        try:
            html = book.read_text(doc)
            lines, anchors, blanks, heads = _extract(
                html, book.css_for(doc, html),
                _Notes(doc, note_ids, note_labels, note_word, note_stars),
                body_style, caption_word,
            )
        except KeyError:
            continue
        entries = per_doc.get(doc, [])
        if not lines:
            # A page with no text at all: a cover, a plate, or a scanned page whose words
            # live in a JPEG. Its TOC entries are NOT dropped (owner 2026-07-29) — they
            # wait here and land on the next page that does have text, so the label
            # survives and jumps as close to where it belongs as a text file allows.
            # Several labels can end up on one page; that is expected and harmless (the
            # earlier ones become headings with no text under them, which this format
            # already uses for part dividers).
            carried.extend(entries)
            continue

        if not entries:
            if not guessed_date and _looks_like_title_page(lines, book):
                guessed_date = _guess_date(lines)
                continue
            if _is_contents_page(lines, toc_labels):
                continue  # the book's own contents list — the one written below replaces it
            if not carried:
                # Not in the book's TOC (some publishers list only the parts, and a blurb
                # or colophon is never listed). Keep every word, but do NOT invent a TOC
                # entry: the .txt must show the same table of contents as the EPUB.
                body.extend(_paragraph_blocks(lines, blanks, indent, heads, trailing_head))
                trailing_head = bool(heads[-1]) if heads else trailing_head
                continue
        # A page that is skipped above (a title page, the book's own contents list) is not
        # a landing site: whatever is waiting stays waiting for a page that is kept.
        entries = carried + entries
        carried = []
        body.extend(_sections_for(entries, lines, anchors, emitted, indent, blanks, heads))
        trailing_head = False  # a section starts with a fence; the fence owns its own spacing

    if carried:
        # Nothing with text left to land on — the book ends in plates. Write the labels as
        # headings with no text rather than losing them from the table of contents.
        body.extend(_sections_for(carried, [], {}, emitted, indent, []))

    cover = cover_jpeg_base64(book) if with_cover else ""
    header = _header_lines(book, path.stem, guessed_date, bool(cover))
    parts = ["\n".join(header)]
    if emitted:
        # Built from the sections we actually wrote, never from the raw nav: a nav entry
        # for the cover image or for the nav document itself has no text to show, and a
        # Contents list that promises a chapter the file does not contain is a lie.
        # The heading is the reader's own word for it — Reboku prints this heading on the
        # contents page it generates, so a Chinese book should not say "Contents".
        contents = [f"--==# {_contents_word(book.language)} #==--"]
        for depth, label in emitted:
            contents.append(f"{'  ' * (depth - 1)}{label}")
        # The Contents block goes immediately BEFORE the first chapter marker, not
        # simply after the header. A reader skips the whole section this heading opens,
        # so anything sitting between it and the first marker is skipped with it. That
        # is not hypothetical: a book whose own TOC lists only its colophon (one sample
        # book lists nothing but its licence page) opens with several hundred thousand
        # characters that are in no TOC entry — placed under this heading they would be
        # thrown away, and 98% of the book would silently vanish. Text that precedes the
        # first marker is written first, where a reader keeps it as an untitled opening
        # chapter. For a normal book the first body element IS a marker, so this changes
        # nothing.
        opening = next((i for i, block in enumerate(body) if _looks_like_mark(block)), len(body))
        parts.extend(body[:opening])
        parts.append("\n".join(contents))
        parts.extend(body[opening:])
    else:
        parts.extend(body)
    if cover:
        parts.append(cover_block(cover))
    return book.title or path.stem, _join_blocks(parts) + "\n"


TOC_LABEL = re.compile(r"^\s*(目次|目錄|目录|Contents|CONTENTS|TOC)\s*[:：]?\s*$")


def _sections_for(
    entries: list[tuple[int, str, str]],
    lines: list[str],
    anchors: dict[str, int],
    emitted: list[tuple[int, str]],
    indent: str = "",
    blanks: list[int] | None = None,
    heads: list[int] | None = None,
) -> list[str]:
    """One document may hold several TOC entries (anchors) — split at them.

    An entry carried over from an earlier text-less page has a fragment that names an
    anchor in *that* page, so it is not found here and starts at line 0 — which is what
    it should do: it points at the top of the first page that has any text. The sort is
    stable, so entries that share a start keep their table-of-contents order and the
    earlier ones simply take an empty slice.
    """
    runs = blanks if blanks is not None else [0] * len(lines)
    kinds = heads if heads is not None else [0] * len(lines)
    starts: list[tuple[int, int, str]] = []  # (line index, depth, label)
    for depth, fragment, label in entries:
        index = anchors.get(fragment, 0) if fragment else 0
        starts.append((index, depth, label))
    starts.sort(key=lambda item: item[0])

    out: list[str] = []
    for position, (index, depth, label) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        chunk = lines[index:end]
        # The blank counts run one-per-paragraph, so every slice and trim below has to
        # happen to both lists or the spacing drifts onto the wrong paragraph.
        chunk_blanks = runs[index:end]
        chunk_heads = kinds[index:end]
        # The document prints its own heading; the label replaces it so the file
        # states each title exactly once.
        if chunk and _norm(chunk[0]) == _norm(label):
            chunk, chunk_blanks, chunk_heads = chunk[1:], chunk_blanks[1:], chunk_heads[1:]
        elif len(chunk) > 1 and _norm(chunk[0] + chunk[1]) == _norm(label):
            chunk, chunk_blanks, chunk_heads = chunk[2:], chunk_blanks[2:], chunk_heads[2:]
        # …and a heading the marker only PARTLY repeats goes too (owner 2026-07-30). Books
        # print their chapter title again at the top of the page, often shortened: the
        # marker says 「法則01　某某標題」 and the page prints 「某某標題」, or
        # 「推薦序　某某某」 and 「推薦序」. Measured across the sample library: 66 of the
        # 131 headings this catches were a shortened repeat like that.
        #
        # ⚠️ Containment is tested EXACTLY, on whitespace-stripped text, and only on a line
        # already decided to be a sub-heading. DO NOT loosen it into any kind of similarity
        # or edit-distance match: one book's marker says 「〈Title〉：subtitle」 while the page
        # prints 「〈Title〉──subtitle」, which is NOT a repeat — it is the book's own subtitle
        # line, and a fuzzy match would delete all 24 of them.
        # A `while`, not an `elif`: a book often sets its title over SEVERAL lines and the
        # marker joins them, so 「Aesop's Fables」 / 「A Selection」 under the marker
        # 「Aesop's Fables: A Selection」 is one repeat spelt in two headings.
        while (chunk and chunk_heads[0] in (SUBHEAD_PLAIN, SUBHEAD_BOXED)
               and _norm(chunk[0]) and _norm(chunk[0]) in _norm(label)):
            chunk, chunk_blanks, chunk_heads = chunk[1:], chunk_blanks[1:], chunk_heads[1:]
        if TOC_LABEL.match(label):
            continue  # the book's own contents page — the header's Contents replaces it
        emitted.append((depth, label))
        out.extend(_section(depth, label, chunk, indent, chunk_blanks, chunk_heads))
    return out


BLANK_BLOCK = ""  # a whitespace-only paragraph from the source: one blank line
STRUCTURE_PREFIX = "--=="  # a chapter fence, the Contents heading, the cover fence


def _join_blocks(blocks: list[str]) -> str:
    """Assemble the file.

    Consecutive body paragraphs are separated by a plain line break and NOTHING else:
    a paragraph is one line, and the indent already shows where it starts. That leaves
    the blank line free to mean what the book meant by it — every empty paragraph in
    the source becomes one blank line here, a run of them a run of blank lines. Spending
    a blank line on every paragraph boundary would both cost half the file and leave
    the book's own spacing with no way to be written down.

    A fence — a chapter marker, the Contents heading, the cover block — always stands
    alone with a blank line either side, so it still reads as a break in Notepad and the
    header still ends at the first blank line.

    Blanks with nothing before them are dropped, which keeps a chapter from opening on
    empty space; a run at the very end has no following block and is never written.
    """
    text = ""
    pending = 0
    previous_structural = True
    for block in blocks:
        if block == BLANK_BLOCK:
            pending += 1
            continue
        structural = block.startswith(STRUCTURE_PREFIX)
        if not text:
            # The first block is the header, which the format ends at the first blank
            # line — so whatever follows it starts one.
            text, previous_structural, pending = block, True, 0
            continue
        text += "\n\n" if structural or previous_structural else "\n" + "\n" * pending
        text += block
        previous_structural = structural
        pending = 0
    return text


MARK_OPEN = "--==#"
MARK_CLOSE = "#==--"


def _looks_like_mark(line: str) -> bool:
    """Would Reboku read this body line as a chapter marker?"""
    return line.startswith(MARK_OPEN) and line.endswith(MARK_CLOSE)


HEADING_RULE = "=" * 20


def _paragraph_blocks(
    paragraphs: list[str],
    blanks: list[int],
    indent: str,
    heads: list[int] | None = None,
    after_heading: bool = False,
) -> list[str]:
    """Body paragraphs with the source's own empty paragraphs restored between them.

    The run in front of the FIRST paragraph is written like any other and dropped later by
    [_join_blocks], which is the only place that knows whether a chapter fence comes before
    it. Dropping it here instead cost a sub-heading its blank line: a chapter split across
    two XHTML files starts its second file at position 0 with no fence in front of it, so
    a sub-heading opening the second file came out glued to the last line of the first.

    A sub-heading (see [_sub_headings]) is written differently from a paragraph, and the
    difference is what tells a reader — and a person in Notepad — that it is one:

        …the paragraph before it.
                                     <- exactly one blank line, never two or three
        小標題                        <- no indent, hard against the left edge
                                     <- exactly one blank line
        　　今天是星期六，…

    and when the book drew a box around the heading, the blank lines become the box:

                                     <- one blank line, so the `=` is not crowded
        ====================
        小標題
        ====================
                                     <- one blank line

    The count is fixed at one on each side rather than "at least one" (owner 2026-07-29):
    a book that already left three empty paragraphs above its heading would otherwise
    strand it in the middle of a hole.
    """
    kinds = heads if heads is not None else [0] * len(paragraphs)
    out: list[str] = []
    # `after_heading` starts True when the PREVIOUS call ended on a heading or a caption: it
    # already wrote the blank line that goes after it, and this call must not write it again.
    # A run of plates, each its own XHTML file with nothing but a caption, is exactly that —
    # every caption is a separate call, and both halves of the blank were being written.
    for position, paragraph in enumerate(paragraphs):
        kind = kinds[position] if position < len(kinds) else 0
        if after_heading:
            runs = 0  # the heading already wrote its own blank line — see below
        elif kind:
            runs = 1
        else:
            runs = blanks[position] if position < len(blanks) else 0
        out.extend([BLANK_BLOCK] * runs)
        if kind == SUBHEAD_BOXED:
            out.extend([HEADING_RULE, _body_line(paragraph, ""), HEADING_RULE])
        else:
            # ⚠️ A caption KEEPS the indent. It is prose about a picture, not a heading, and
            # in this format an un-indented line means "sub-heading" — writing it flush would
            # make every caption come out as a bold heading in the reader.
            out.append(_body_line(paragraph, indent if kind in (0, CAPTION) else ""))
        if kind:
            # ⚠️ The blank line AFTER a heading is written here, with the heading, and NOT
            # left to the next paragraph to write. A chapter is often split across XHTML
            # files right at this seam — one book ends a file with its 「CHAPTER 11」 label
            # and opens the next with the prose — and each file is a separate call, so
            # anything remembered in a local variable never arrives. `_join_blocks` drops a
            # trailing run at the end of the file, so this cannot leave a hole either.
            out.append(BLANK_BLOCK)
        after_heading = bool(kind)
    return out


def _section(depth: int, label: str, paragraphs: list[str], indent: str = "",
             blanks: list[int] | None = None, heads: list[int] | None = None) -> list[str]:
    """`--==# Title #==--`, one `#` per TOC level.

    The fence is deliberately unusual: a real title or a line of body text can start and
    end with `=`, `#` or `*`, but never with `--==#` ... `#==--`. And in the impossible
    case that a paragraph does, it is indented by one space — Reboku only reads a marker
    at column 0, so the escape is lossless and invisible to the eye.
    """
    marks = "#" * min(max(1, depth), MAX_HEADING_LEVEL)
    blocks = [f"--=={marks} {label} {marks}==--"]
    blocks.extend(_paragraph_blocks(paragraphs, blanks or [0] * len(paragraphs), indent, heads))
    return blocks


# ------------------------------------------------------------------- job model


def _books_in(folder: Path, recurse: bool) -> list[Path]:
    """The .epub files of a folder, sorted. Suffix is matched case-insensitively
    so a `.EPUB` from an old exporter is not silently skipped on Linux."""
    walk = folder.rglob("*") if recurse else folder.iterdir()
    return sorted(p for p in walk if p.is_file() and p.suffix.lower() == ".epub")


def target_for(book: Path, root: Path | None, outdir: Path | None) -> Path:
    """Where `book` lands. Same name as the source, always.

    No `-o`: beside the book. With `-o` and a `root`: under the output folder at the
    same relative position, so sub-folders survive the trip (and two books of the
    same name in different sub-folders cannot collide). `root=None` is the flat
    layout — every .txt straight into the output folder, no sub-folders.
    """
    if outdir is None:
        return book.with_suffix(".txt")
    if root is None:
        return outdir / (book.stem + ".txt")
    return outdir / book.relative_to(root).with_suffix(".txt")


def plan(source: Path, recurse: bool, outdir: Path | None, mirror: bool = True) -> list[tuple[Path, Path]]:
    """[(book, its .txt)] for a single file or a whole folder."""
    if source.is_file():
        return [(source, target_for(source, None, outdir))]
    root = source if mirror else None
    return [(b, target_for(b, root, outdir)) for b in _books_in(source, recurse)]


def convert_to(book: Path, dst: Path, with_cover: bool = True) -> tuple[str, int]:
    """Convert one book onto disk. Returns (title, characters written)."""
    title, text = convert(book, with_cover)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: the BOM makes Notepad show CJK correctly on every Windows build,
    # and Reboku treats a BOM as a declaration (never a guess).
    dst.write_text(text, encoding="utf-8-sig")
    return title, len(text)


# ------------------------------------------------- text book, or one image per page?

# A comic or a scanned book has no text to extract, so converting it would write an
# all-but-empty .txt. Telling one from a text book is done by counting, not guessing:
# a page holding exactly one picture and almost no words is a "single-image page", and
# a book made mostly of those is a picture book. The thresholds below were measured
# against a real library — picture books score 99%+ single-image pages, text books
# 7-18%, and the worst case (a 54-page text book carrying 74 illustrations) scores
# 37%. The 70% line sits in the middle of a 60-point empty gap, so it is not delicate.
ENTRY_SIZE_CAP = 16 * 1024  # a bigger entry cannot be a single-image wrapper page
VISIBLE_TEXT_LIMIT = 100

HEAD_BLOCK = re.compile(r"(?is)<head\b.*?</head>")
STYLE_OR_SCRIPT = re.compile(r"(?is)<(style|script)\b.*?</\1>")
ANY_TAG = re.compile(r"(?s)<[^>]*>")
ENTITY_REFERENCE = re.compile(r"&[a-zA-Z#0-9]+;")
IMAGE_REFERENCE = re.compile(r"(?i)<im(?:g|age)\b")


def visible_text_length(markup: str) -> int:
    """Visible characters of a page's raw markup: head/style/script gone, tags and
    entities gone, whitespace not counted."""
    for pattern in (HEAD_BLOCK, STYLE_OR_SCRIPT, ANY_TAG, ENTITY_REFERENCE):
        markup = pattern.sub(" ", markup)
    return sum(1 for character in markup if not character.isspace())


def page_is_single_image(markup: str) -> bool:
    """Exactly one image reference and almost no text — a page that is just a picture."""
    return (len(IMAGE_REFERENCE.findall(markup)) == 1
            and visible_text_length(markup) < VISIBLE_TEXT_LIMIT)


def image_book_verdict(spine_count: int, single_image_count: int, pre_paginated: bool) -> bool:
    """A fixed-layout book must be single-image on EVERY page to count as a comic
    (a text page means it is a laid-out text book); a reflowable one needs at least
    three such pages and at least 70% of the spine."""
    if spine_count <= 0:
        return False
    if pre_paginated:
        return single_image_count == spine_count
    return single_image_count >= 3 and single_image_count * 10 >= spine_count * 7


def is_image_book(path: Path) -> bool:
    """One picture per page (a comic, a scan) — nothing for this converter to extract.

    A book that cannot even be opened returns False on purpose: it stays in the
    queue so the converter reports the real error, instead of vanishing silently.
    """
    try:
        book = Epub(path)
        spine = [item_id for item_id in book.spine if item_id in book.items]
        single = 0
        for item_id in spine:
            name = book.item_path(item_id)
            # Over the cap it is a text page by definition, and is never read.
            if book.entry_size(name) > ENTRY_SIZE_CAP:
                continue
            try:
                markup = book.read_text(name)
            except KeyError:
                continue  # a page we cannot read counts as a text page, never a picture
            if page_is_single_image(markup):
                single += 1
        return image_book_verdict(len(spine), single, book.pre_paginated)
    except Exception:  # noqa: BLE001 - a book we cannot judge is treated as text
        return False


class OverwritePolicy:
    """Answers "may I overwrite this?", remembering an all/none answer.

    Asking is delegated (console prompt or dialog box) so the batch runner below
    is the same code for both front ends.
    """

    def __init__(self, ask, force: bool = False) -> None:  # type: ignore[no-untyped-def]
        self._ask = ask  # (Path) -> "yes" | "no" | "all" | "none" | "quit"
        self._standing: str | None = "all" if force else None

    def verdict(self, dst: Path) -> str:
        """"yes" (write it), "no" (skip it) or "quit" (abandon the batch)."""
        if not dst.exists():
            return "yes"
        if self._standing is None:
            answer = self._ask(dst)
            if answer in ("all", "none"):
                self._standing = answer
            elif answer in ("yes", "no", "quit"):
                return answer
            else:
                return "no"  # an unexpected answer must never overwrite
        return "yes" if self._standing == "all" else "no"


def run(jobs, policy: OverwritePolicy, report, stop=None, with_cover: bool = True) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Convert every job, reporting each outcome.

    `report(kind, book, dst, detail)` is called with kind "start"/"ok"/"skip"/
    "fail"/"stopped"; `stop()` (optional) lets the GUI's Stop button end the run
    between books — never mid-write, so no half-finished .txt is left behind.
    """
    tally = {"ok": 0, "skip": 0, "fail": 0}
    for book, dst in jobs:
        if stop is not None and stop():
            report("stopped", book, dst, "")
            break
        verdict = policy.verdict(dst)
        if verdict == "quit":
            report("stopped", book, dst, "")
            break
        if verdict == "no":
            tally["skip"] += 1
            report("skip", book, dst, "")
            continue
        report("start", book, dst, "")
        try:
            title, size = convert_to(book, dst, with_cover)
        except Exception as error:  # noqa: BLE001 - one bad book must not stop the batch
            tally["fail"] += 1
            report("fail", book, dst, str(error))
            continue
        tally["ok"] += 1
        report("ok", book, dst, f"{title} ({size:,} chars)")
    return tally


# ------------------------------------------------------------------------ CLI


def _ask_console(dst: Path) -> str:
    """Nobody at the keyboard (a pipe, a scheduled run) can answer, so nothing is
    overwritten: it keeps every existing file and says so at the end."""
    if not sys.stdin or not sys.stdin.isatty():
        return "none"
    print(f"\n  Already exists: {dst}")
    while True:
        try:
            reply = input("  Overwrite? [y]es [n]o [a]ll [s]kip all [q]uit: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "none"  # asked once, no answer coming — keep the rest too
        answer = {"y": "yes", "n": "no", "a": "all", "s": "none", "q": "quit"}.get(reply[:1])
        if answer:
            return answer


def _report_console(kind: str, book: Path, dst: Path, detail: str) -> None:
    if kind == "start":
        print(f"Converting: {book.name} ... ", end="", flush=True)
    elif kind == "ok":
        print(f"OK -> {dst.name}  {detail}")
    elif kind == "fail":
        print(f"FAILED: {detail}")
    elif kind == "skip":
        print(f"Kept existing: {dst.name}")
    elif kind == "stopped":
        print("Stopped.")


def _use_parent_console() -> None:
    """Windows: borrow the terminal we were started from, if there is one.

    The .exe is built as a windowed program, so Windows never creates a console for
    it — a double-click opens the window with no black box flashing first. That also
    means the command line would have nowhere to print, so when the program IS started
    from a terminal it attaches to that terminal and reopens the standard streams onto
    it. A stream that is already connected (output redirected to a file or a pipe) is
    left exactly as it is.

    With no console to attach to, the streams stay None; `print` writes nothing rather
    than failing, which is what a double-click should do.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        if not ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return  # not started from a terminal — nothing to print to
    except Exception:  # noqa: BLE001 - no console is not an error
        return
    for name, device, mode in (("stdin", "CONIN$", "r"), ("stdout", "CONOUT$", "w"),
                               ("stderr", "CONOUT$", "w")):
        if getattr(sys, name, None) is not None:
            continue  # already redirected somewhere real — do not steal it
        try:
            setattr(sys, name, open(device, mode, encoding="utf-8",
                                    errors="replace", buffering=1))
        except OSError:
            pass


def _pause() -> None:
    """Keep the window open after a drag & drop run — but never block a pipe."""
    if not sys.stdout or not sys.stdout.isatty():
        return
    try:
        import msvcrt  # Windows only: drag & drop leaves no console to read
    except ImportError:
        return
    print("\nPress any key to close...")
    msvcrt.getch()


def _run_cli(args) -> int:  # type: ignore[no-untyped-def]
    source: Path = args.source
    if source.is_file() and source.suffix.lower() != ".epub":
        print(f"Not an .epub file: {source}")
        return 1
    if not source.exists():
        print(f"No such file or folder: {source}")
        return 1

    jobs = plan(source, args.recurse, args.output, not args.flat)
    if not jobs:
        print("No .epub files found.")
        if source.is_dir() and not args.recurse and _books_in(source, True):
            print("(There are books in sub-folders — add -r to include them.)")
        return 1
    if source.is_dir() and not args.recurse:
        deeper = len(_books_in(source, True)) - len(jobs)
        if deeper > 0:
            print(f"Note: {deeper} more book(s) in sub-folders, ignored without -r.")

    print(f"Found {len(jobs)} book(s)")
    if not pillow_available() and not args.no_cover:
        print("Note: Pillow is not installed — books are converted without a cover "
              "(Cover: False). `pip install pillow` to embed one.")
    # Comics and scans hold no text to extract, so they are reported once, up front,
    # rather than converted into an empty .txt.
    images = [book for book, _dst in jobs if is_image_book(book)]
    if images:
        print(f"\nSkipping {len(images)} image-only book(s) — nothing to extract:")
        for book in images:
            print(f"  {book.name}")
        skip_set = {str(book) for book in images}
        jobs = [job for job in jobs if str(job[0]) not in skip_set]
        if not jobs:
            return 0
    print()
    tally = run(jobs, OverwritePolicy(_ask_console, args.force), _report_console,
                with_cover=not args.no_cover)
    print(f"\nFinished: {tally['ok']} converted, {tally['skip']} kept, "
          f"{tally['fail']} failed, {len(images)} image-only.")
    return 1 if tally["fail"] else 0


def main() -> None:
    _use_parent_console()  # before anything can try to print
    # Book titles are CJK; a legacy console/pipe encoding must not kill the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - older/odd streams simply keep their encoding
            pass

    parser = argparse.ArgumentParser(
        prog="EPUB2txt",
        description="Convert EPUB books into Reboku plain-text books (.txt).",
        epilog="With no source at all the window (GUI) opens instead.",
    )
    parser.add_argument("source", nargs="?", type=Path,
                        help="an .epub file or a folder of them")
    parser.add_argument("-o", "--output", type=Path, metavar="DIR",
                        help="output folder (default: beside each book); a folder "
                             "source keeps its sub-folder structure")
    parser.add_argument("-r", "--recurse", action="store_true",
                        help="also convert books in sub-folders")
    parser.add_argument("-f", "--force", action="store_true",
                        help="overwrite existing .txt without asking")
    parser.add_argument("--flat", action="store_true",
                        help="put every .txt straight into -o, without rebuilding the "
                             "source sub-folder structure")
    parser.add_argument("--no-cover", action="store_true",
                        help="do not embed the cover picture (the header then says "
                             "Cover: False)")
    parser.add_argument("--gui", action="store_true",
                        help="open the window even though a source was given")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in checks and exit")
    args = parser.parse_args()

    if args.self_test:
        # The checks live in `selftest.py`, imported here so that this file stays the whole
        # program: a release ships EPUB2txt.py on its own, and the tests are a development
        # file that goes with the source.
        try:
            import selftest
        except ImportError:
            print("selftest.py is not part of this distribution — nothing to run.")
            print("It lives with the source: https://github.com/Dino9021/Reboku_EPUB2txt")
            return
        selftest.run()
        print("self-test OK")
        return
    if args.source is None or args.gui:
        # No source given: the window reopens on the folder it was last left at.
        run_gui(args.source, args.output)
        return

    code = _run_cli(args)
    _pause()
    sys.exit(code)


# ------------------------------------------------------------------------ GUI

# One table per language, same keys, so every visible word has a single home. No i18n
# machinery: two dicts and a module-level `TEXT` that points at the one in force.
#
# The language follows the OPERATING SYSTEM: Chinese if the system says Chinese, English
# otherwise (owner 2026-07-30). A tool that opens in a language you cannot read is worse than
# one that opens in English, and English is the safe default for everyone else. The window has
# a switch, and the choice is remembered.
TEXT_ZH = {
    "lang_label": "語言",
    "lang_zh": "中文",
    "lang_en": "English",
    "title": "EPUB2txt — Reboku 純文字書轉換器",
    "source": "來源",
    "output": "輸出",
    "browse": "瀏覽",
    "same_as_source": "與來源同資料夾",
    "mirror": "複製來源資料夾結構",
    "with_cover": "包含書籍封面圖片",
    "refresh": "重新整理",
    "found": "來源清單(勾選要轉換的書)",
    "queue": "轉換佇列",
    "add": "加入 →",
    "remove": "← 移除",
    "clear": "清空",
    "start": "開始轉換",
    "stop": "停止",
    "col_book": "書檔",
    "col_size": "大小",
    "col_target": "輸出檔",
    "col_status": "狀態",
    "st_waiting": "待轉換",
    "st_working": "轉換中…",
    "st_done": "完成",
    "st_skipped": "跳過(已存在)",
    "st_failed": "失敗",
    "log": "執行狀態",
    "overwrite_title": "檔案已存在",
    "overwrite_body": "目的檔已經存在,要覆寫嗎?\n\n{path}",
    "yes": "是",
    "no": "否",
    "all": "全部是",
    "none": "全部否",
    "no_source": "請先選一個資料夾。",
    "no_checked": "左邊還沒有勾選任何書。",
    "no_jobs": "佇列是空的,先把左邊勾選的書加進來。",
    "opened": "開啟 {path}",
    "checking": "檢查書籍類型 {done} / {total}",
    "queued": "佇列 {count} 本,開始轉換",
    "finished": "完成 {ok} 本,跳過 {skip} 本,失敗 {fail} 本",
    "busy": "轉換還在進行中,要停止並關閉嗎?",
    "busy_lang": "轉換還在進行中,等它跑完或先按停止,再切換語言。",
    "busy_title": "轉換中",
    "image_title": "略過圖片型書籍",
    "image_body": "下列 {count} 本是一頁一圖的圖片型書籍(漫畫、掃描書),裡面沒有可抽出的文字,已經不加入佇列:\n\n{names}",
    "image_more": "…另外還有 {count} 本,完整清單見下方狀態記錄。",
    "image_log": "略過(圖片型書籍,無可抽取文字):{name}",
    "no_pillow": "沒裝 Pillow,轉出的書不會夾帶封面(Cover: False);要封面請執行 pip install pillow",
}

TEXT_EN = {
    "lang_label": "Language",
    "lang_zh": "中文",
    "lang_en": "English",
    "title": "EPUB2txt — Reboku plain-text book converter",
    "source": "From",
    "output": "To",
    "browse": "Browse",
    "same_as_source": "Beside each book",
    "mirror": "Keep the source folder structure",
    "with_cover": "Include the book's cover image",
    "refresh": "Refresh",
    "found": "Books found (tick the ones to convert)",
    "queue": "Queue",
    "add": "Add →",
    "remove": "← Remove",
    "clear": "Clear",
    "start": "Convert",
    "stop": "Stop",
    "col_book": "Book",
    "col_size": "Size",
    "col_target": "Output file",
    "col_status": "Status",
    "st_waiting": "Waiting",
    "st_working": "Converting…",
    "st_done": "Done",
    "st_skipped": "Skipped (already there)",
    "st_failed": "Failed",
    "log": "Progress",
    "overwrite_title": "File already exists",
    "overwrite_body": "The output file is already there. Overwrite it?\n\n{path}",
    "yes": "Yes",
    "no": "No",
    "all": "Yes to all",
    "none": "No to all",
    "no_source": "Pick a folder first.",
    "no_checked": "Nothing is ticked on the left.",
    "no_jobs": "The queue is empty — add the books you ticked on the left.",
    "opened": "Opened {path}",
    "checking": "Checking book types {done} / {total}",
    "queued": "{count} in the queue, starting",
    "finished": "{ok} converted, {skip} skipped, {fail} failed",
    "busy": "A conversion is still running. Stop it and close?",
    "busy_lang": "A conversion is still running — let it finish or press Stop, then switch.",
    "busy_title": "Converting",
    "image_title": "Picture books skipped",
    "image_body": "These {count} are one-image-per-page picture books (comics, scans). There is no text in them to extract, so they were not added to the queue:\n\n{names}",
    "image_more": "…and {count} more; the full list is in the progress log below.",
    "image_log": "Skipped (picture book, no text to extract): {name}",
    "no_pillow": "Pillow is not installed, so books convert without their cover (Cover: False). For covers: pip install pillow",
}

# The table in force. Swapped by [_use_language] — every `TEXT[...]` in the window reads it.
TEXT = TEXT_ZH


def _system_language() -> str:
    """`zh` when the operating system is set to Chinese, `en` for everything else.

    ⚠️ The **display** language is what decides, not the region. On Windows those are two
    separate settings: a machine can be set to English menus with Taiwanese dates, or the other
    way round, and the question here is which language the person reads — so
    `GetUserDefaultUILanguage` is asked first and `GetUserDefaultLocaleName` (the region) only
    as a fallback. Every Chinese variant — Taiwan, Hong Kong, Macau, mainland, Singapore —
    shares the primary language id `LANG_CHINESE` (0x04), which is the whole test; there is no
    list of locale names to keep up to date.

    When nothing answers, English is the safe default: it is the one a reader of any language
    can at least navigate, and the window has a switch in plain sight.
    """
    import locale

    names = []
    if os.name == "nt":
        try:
            import ctypes

            ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if ui & 0x3FF == 0x04:  # LANG_CHINESE, any region
                return "zh"
            if ui:
                return "en"
        except (AttributeError, OSError):
            pass
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                names.append(buf.value)
        except (AttributeError, OSError):
            pass
    try:
        names.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    for name in names + [os.environ.get("LANG", ""), os.environ.get("LC_ALL", "")]:
        tag = name.replace("_", "-").lower()
        if tag.startswith("zh") or "chinese" in tag or "hant" in tag or "hans" in tag:
            return "zh"
    return "en"


def _use_language(code: str) -> str:
    """Point [TEXT] at one of the tables. Returns the code actually in force."""
    global TEXT
    TEXT = TEXT_EN if code == "en" else TEXT_ZH
    return "en" if code == "en" else "zh"


def _fmt_size(size: int) -> str:
    return f"{size / 1024:,.0f} KB" if size < 1024 * 1024 else f"{size / 1048576:.1f} MB"


# Where the window remembers the folder you were last looking at. Kept out of the
# repo folder on purpose — this file is per-machine scratch, not part of the tool.
STATE_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "EPUB2txt" / "state.json"


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # first run, or a state file someone edited into nonsense


def _default_source() -> Path:
    """Where a first run starts browsing: the drive root, so the whole machine is one
    expand away rather than an empty window with nothing to click."""
    return Path(os.environ.get("SystemDrive", "C:") + os.sep) if os.name == "nt" else Path("/")


def _default_output() -> Path:
    """Where a first run writes: the user's Documents. Home itself if there is no
    Documents folder (it can be renamed, or redirected somewhere we cannot guess)."""
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # remembering the path is a convenience, never a reason to fail


FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def _is_visible(entry: Path) -> bool:
    """What a file browser would show. The drive root is full of hidden system
    entries ($Recycle.Bin, System Volume Information, the legacy junctions that
    raise on any access) and none of them ever holds a book."""
    if os.name != "nt":
        return not entry.name.startswith(".")
    try:
        attributes = os.lstat(entry).st_file_attributes  # type: ignore[attr-defined]
    except OSError:
        return False  # cannot even stat it — nothing worth listing
    return not attributes & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)


CHECK_GLYPH = {"on": "[v]", "part": "[-]", "off": "[ ]"}
PLACEHOLDER = "\x00"  # the dummy child that gives an unopened folder its expander arrow


class _Gui:
    """FileZilla-shaped: a checkable folder tree on the left, the transfer queue on
    the right, a live log across the bottom. Conversion runs on one worker thread so
    the window keeps repainting; the thread talks back through `self.events`."""

    def __init__(self, root, source: Path | None, output: Path | None) -> None:  # type: ignore[no-untyped-def]
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.jobs: dict[str, tuple[Path, Path]] = {}  # queue rows, keyed by source path
        self.checked: set[str] = set()  # ticked .epub paths
        self.loaded: set[str] = set()  # folder rows whose children are already listed
        self.books_under: dict[str, list[Path]] = {}  # folder -> its books, all the way down
        self.root_dir: Path | None = None
        self.events: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker: threading.Thread | None = None
        self.pending_answer: queue.Queue | None = None  # a dialog the worker waits on

        state = _load_state()
        # The language before a single widget is built: whatever was chosen last, else what
        # the operating system is set to (owner 2026-07-30).
        self.lang = _use_language(state.get("lang") or _system_language())
        self.relaunch = False
        # An -o on the command line is an explicit instruction and outranks what was
        # remembered; only when it is absent does the last session's choice apply.
        # A first run unticks "same as source" so the Documents default below is the
        # one actually in force — with the drive root as the source, writing beside
        # each book would scatter .txt files across the whole disk.
        same = False if (output is not None or not state) else bool(state.get("same", True))
        if source is None:
            source = Path(state["source"]) if state.get("source") else _default_source()
        if output is None:
            output = Path(state["output"]) if state.get("output") else _default_output()

        root.title(TEXT["title"])
        root.geometry("800x600")
        root.minsize(680, 480)

        self.source_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value=str(output) if output else "")
        self.same_var = tk.BooleanVar(value=same)
        self.mirror_var = tk.BooleanVar(value=bool(state.get("mirror", True)))
        self.cover_var = tk.BooleanVar(value=bool(state.get("cover", True)))
        self.count_var = tk.StringVar(value="")

        self._build_paths()
        self._build_panes()
        self._build_actions()
        self._sync_output_state()
        if source:
            # A file was passed in (--gui book.epub): show its folder, tick that book.
            self.open_folder(source if source.is_dir() else source.parent)
            if source.is_file():
                self.checked.add(str(source))
                self._refresh_labels()
        if not pillow_available():
            self.write_log(TEXT["no_pillow"])
        self.balance_panes()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick = root.after(80, self._drain)

    # -- layout
    def _build_paths(self) -> None:
        ttk, tk = self.ttk, self.tk
        bar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text=TEXT["source"]).grid(row=0, column=0, sticky="w", padx=(0, 6))
        source_entry = ttk.Entry(bar, textvariable=self.source_var)
        source_entry.grid(row=0, column=1, sticky="ew")
        source_entry.bind("<Return>", lambda _event: self._open_typed())
        ttk.Button(bar, text=TEXT["browse"], command=self._pick_source).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(bar, text=TEXT["refresh"], command=self._reopen).grid(row=0, column=3, padx=(4, 0))

        # The language switch sits with the paths rather than in a menu: this window has no
        # menu bar, and someone who opened it in the wrong language needs to SEE the way out.
        lang = ttk.Frame(bar)
        lang.grid(row=0, column=4, padx=(10, 0))
        ttk.Label(lang, text=TEXT["lang_label"]).pack(side="left", padx=(0, 4))
        self.lang_var = tk.StringVar(value=TEXT["lang_zh"] if self.lang == "zh" else TEXT["lang_en"])
        picker = ttk.Combobox(lang, textvariable=self.lang_var, state="readonly", width=8,
                              values=(TEXT["lang_zh"], TEXT["lang_en"]))
        picker.pack(side="left")
        picker.bind("<<ComboboxSelected>>", self._switch_language)

        ttk.Label(bar, text=TEXT["output"]).grid(row=1, column=0, sticky="w", pady=(6, 0), padx=(0, 6))
        self.output_entry = ttk.Entry(bar, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.output_button = ttk.Button(bar, text=TEXT["browse"], command=self._pick_output)
        self.output_button.grid(row=1, column=2, pady=(6, 0), padx=(6, 0))

        options = ttk.Frame(bar)
        options.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(options, text=TEXT["same_as_source"], variable=self.same_var,
                        command=self._sync_output_state).pack(side="left")
        self.mirror_check = ttk.Checkbutton(options, text=TEXT["mirror"], variable=self.mirror_var,
                                            command=self.refresh_targets)
        self.mirror_check.pack(side="left", padx=(14, 0))
        # The cover has nothing to do with where the file lands, so it stays enabled
        # even when the output box is greyed out.
        ttk.Checkbutton(options, text=TEXT["with_cover"],
                        variable=self.cover_var).pack(side="left", padx=(14, 0))

    def _build_panes(self) -> None:
        ttk = self.ttk
        outer = self.outer_panes = ttk.Panedwindow(self.root, orient="vertical")
        outer.pack(fill="both", expand=True, padx=8, pady=4)

        top = self.top_panes = ttk.Panedwindow(outer, orient="horizontal")
        left = ttk.Labelframe(top, text=TEXT["found"], padding=4)
        middle = ttk.Frame(top, padding=(4, 40))
        right = ttk.Labelframe(top, text=TEXT["queue"], padding=4)
        top.add(left, weight=1)
        top.add(middle)
        top.add(right, weight=1)

        self.found_tree = self._tree(left, {"#0": TEXT["col_book"], "size": TEXT["col_size"]},
                                     widths={"#0": 240, "size": 80})
        # A tick box is the whole point of this pane, so a click on a row toggles it;
        # only the expander arrow keeps its usual open/close job.
        self.found_tree.bind("<Button-1>", self._on_click)
        self.found_tree.bind("<<TreeviewOpen>>", self._on_open)

        for label, command in ((TEXT["add"], self.add_checked), (TEXT["remove"], self.remove_selected),
                               (TEXT["clear"], self.clear_queue)):
            ttk.Button(middle, text=label, width=9, command=command).pack(pady=3)

        self.queue_tree = self._tree(
            right,
            {"#0": TEXT["col_book"], "target": TEXT["col_target"], "status": TEXT["col_status"]},
            widths={"#0": 150, "target": 200, "status": 110},
        )
        self.queue_tree.bind("<Double-1>", self._open_output)

        log_box = ttk.Labelframe(outer, text=TEXT["log"], padding=4)
        self.log = self.tk.Text(log_box, height=6, wrap="none", state="disabled")
        self._scrollable(log_box, self.log, self.log.yview, self.log.xview)

        outer.add(top, weight=3)
        outer.add(log_box, weight=1)

    def _tree(self, parent, columns: dict[str, str], widths: dict[str, int]):  # type: ignore[no-untyped-def]
        ttk = self.ttk
        data_columns = [key for key in columns if key != "#0"]
        tree = ttk.Treeview(parent, columns=data_columns, selectmode="extended", height=8)
        for key, heading in columns.items():
            tree.heading(key, text=heading)
            # No column stretches: every one keeps the width it was given, and anything
            # wider than the pane is reached with the scrollbar (or by dragging the
            # column edge) instead of being silently clipped.
            tree.column(key, width=widths.get(key, 100), stretch=False, anchor="w")
        self._scrollable(parent, tree, tree.yview, tree.xview)
        return tree

    def _scrollable(self, parent, widget, yview, xview) -> None:  # type: ignore[no-untyped-def]
        """Put `widget` in `parent` with a scrollbar on both axes."""
        ttk = self.ttk
        vertical = ttk.Scrollbar(parent, orient="vertical", command=yview)
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=xview)
        widget.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

    def balance_panes(self, tries: int = 20) -> None:
        """Place the sashes by hand, once.

        A Panedwindow weight only shares out SPARE space, so the first layout follows
        each pane's requested width — and the queue's three columns are wider than the
        source tree's two, which left the window lopsided. Splitting the two panes down
        the middle and giving the log a third of the height is what "balanced" means
        here; the user can drag either sash afterwards.
        """
        self.root.update_idletasks()
        width = self.top_panes.winfo_width()
        if width < 200:  # called before the window reached the screen — wait for it
            if tries:
                self.root.after(30, lambda: self.balance_panes(tries - 1))
            return
        gap = self.top_panes.sashpos(1) - self.top_panes.sashpos(0)  # the button column
        left = max(140, (width - gap) // 2)
        self.top_panes.sashpos(0, left)
        self.top_panes.sashpos(1, left + gap)
        self.outer_panes.sashpos(0, int(self.outer_panes.winfo_height() * 0.66))

    def _build_actions(self) -> None:
        ttk = self.ttk
        row = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        row.pack(fill="x")
        self.start_button = ttk.Button(row, text=TEXT["start"], command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(row, text=TEXT["stop"], command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 12))
        self.progress = ttk.Progressbar(row, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        ttk.Label(row, textvariable=self.count_var, width=16, anchor="e").pack(side="left", padx=(8, 0))

    # -- paths
    def _sync_output_state(self) -> None:
        # "Same folder as the source" already answers where every .txt goes, so the
        # output box and the structure question have nothing left to decide.
        state = "disabled" if self.same_var.get() else "normal"
        self.output_entry.configure(state=state)
        self.output_button.configure(state=state)
        self.mirror_check.configure(state=state)
        self.refresh_targets()

    def _pick_source(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory(initialdir=str(self.root_dir) if self.root_dir else None)
        if chosen:
            self.open_folder(Path(chosen))

    def _open_typed(self) -> None:
        value = self.source_var.get().strip()
        if value:
            self.open_folder(Path(value))

    def _reopen(self) -> None:
        if self.root_dir:
            self.open_folder(self.root_dir)

    def _pick_output(self) -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory()
        if chosen:
            self.output_var.set(chosen)
            self.refresh_targets()

    def _outdir(self) -> Path | None:
        if self.same_var.get():
            return None
        value = self.output_var.get().strip()
        return Path(value) if value else None

    def _mirror_root(self) -> Path | None:
        """The folder targets are made relative to — None means a flat output."""
        return self.root_dir if self.mirror_var.get() else None

    # -- the source tree
    def open_folder(self, folder: Path) -> None:
        """Point the tree at `folder`. Only folders and .epub files are listed, and
        each row carries a tick box; sub-folders fill in when you open them."""
        from tkinter import messagebox
        if not folder.is_dir():
            messagebox.showerror(TEXT["title"], f"{TEXT['no_source']}\n{folder}")
            return
        tree = self.found_tree
        tree.delete(*tree.get_children())
        self.checked.clear()
        self.loaded.clear()
        self.books_under.clear()
        self.root_dir = folder
        self.source_var.set(str(folder))
        iid = str(folder)
        tree.insert("", "end", iid=iid, text=self._label(folder), values=("",), open=True)
        self.loaded.add(iid)
        self._populate(iid, folder)
        self.write_log(TEXT["opened"].format(path=folder))

    def _populate(self, parent: str, folder: Path) -> None:
        tree = self.found_tree
        try:
            entries = list(folder.iterdir())
        except OSError:
            return  # unreadable folder (permissions, a disconnected drive) — show it empty
        folders, books = [], []
        for entry in entries:
            if not _is_visible(entry):
                continue
            if entry.is_dir():
                folders.append(entry)
            elif entry.suffix.lower() == ".epub" and entry.is_file():
                books.append(entry)
        for sub in sorted(folders, key=lambda p: p.name.lower()):
            iid = tree.insert(parent, "end", iid=str(sub), text=self._label(sub), values=("",))
            # A dummy child gives the arrow; the real listing waits until it is opened,
            # so pointing at a big library does not walk the whole disk.
            tree.insert(iid, "end", iid=iid + PLACEHOLDER, text="")
        for book in sorted(books, key=lambda p: p.name.lower()):
            try:
                size = _fmt_size(book.stat().st_size)
            except OSError:
                size = ""
            tree.insert(parent, "end", iid=str(book), text=self._label(book), values=(size,))

    def _on_open(self, _event) -> None:  # type: ignore[no-untyped-def]
        iid = self.found_tree.focus()
        if not iid or iid in self.loaded:
            return
        self.loaded.add(iid)
        placeholder = iid + PLACEHOLDER
        if self.found_tree.exists(placeholder):
            self.found_tree.delete(placeholder)
        self._populate(iid, Path(iid))

    def _on_click(self, event) -> None:  # type: ignore[no-untyped-def]
        tree = self.found_tree
        if tree.identify_element(event.x, event.y) == "Treeitem.indicator":
            return  # the expander arrow keeps its own job
        iid = tree.identify_row(event.y)
        if iid and not iid.endswith(PLACEHOLDER):
            self._toggle(iid)

    def _all_books_under(self, folder: Path) -> list[Path]:
        key = str(folder)
        found = self.books_under.get(key)
        if found is None:
            # Same filter as the listing, so ticking a folder can never pull in a book
            # the tree does not show. (The CLI has no listing, so -r keeps taking all.)
            found = [book for book in _books_in(folder, True) if _is_visible(book)]
            self.books_under[key] = found
        return found

    def _state(self, path: Path) -> str:
        """A file is on or off; a folder is on when every book under it is ticked,
        part when only some are. A folder with nothing ticked inside is answered from
        the tick set alone — no folder is walked until it actually holds a tick."""
        key = str(path)
        if not path.is_dir():
            return "on" if key in self.checked else "off"
        prefix = key + os.sep
        if not any(ticked.startswith(prefix) for ticked in self.checked):
            return "off"
        books = self._all_books_under(path)
        return "on" if books and all(str(b) in self.checked for b in books) else "part"

    def _label(self, path: Path) -> str:
        return f"{CHECK_GLYPH[self._state(path)]} {path.name or str(path)}"

    def _refresh_labels(self, parent: str = "") -> None:
        for iid in self.found_tree.get_children(parent):
            if iid.endswith(PLACEHOLDER):
                continue
            self.found_tree.item(iid, text=self._label(Path(iid)))
            self._refresh_labels(iid)

    def _toggle(self, iid: str) -> None:
        path = Path(iid)
        if path.is_dir():
            keys = {str(book) for book in self._all_books_under(path)}
            if keys and keys <= self.checked:
                self.checked -= keys  # fully ticked -> clear the whole branch
            else:
                self.checked |= keys
        elif iid in self.checked:
            self.checked.discard(iid)
        else:
            self.checked.add(iid)
        self._refresh_labels()

    # -- the queue
    def refresh_targets(self) -> None:
        """The output folder changed — recompute where every queued book lands."""
        if not self.jobs:
            return
        outdir = self._outdir()
        for key, (book, _old) in list(self.jobs.items()):
            target = target_for(book, self._mirror_root(), outdir)
            self.jobs[key] = (book, target)
            if self.queue_tree.exists(key):
                self.queue_tree.set(key, "target", str(target))

    def add_checked(self) -> None:
        from tkinter import messagebox
        if not self.checked:
            messagebox.showinfo(TEXT["title"], TEXT["no_checked"])
            return
        books = [Path(key) for key in sorted(self.checked) if key not in self.jobs]
        outdir = self._outdir()
        skipped: list[Path] = []
        for index, book in enumerate(books, 1):
            # Comics and scans hold no text, so they never reach the queue. Checking
            # costs ~20ms a book, so say where we are rather than look frozen.
            if len(books) > 4:
                self.count_var.set(TEXT["checking"].format(done=index, total=len(books)))
                self.root.update_idletasks()
            if is_image_book(book):
                skipped.append(book)
                self.write_log(TEXT["image_log"].format(name=book.name))
                continue
            key = str(book)
            target = target_for(book, self._mirror_root(), outdir)
            self.jobs[key] = (book, target)
            self.queue_tree.insert("", "end", iid=key, text=book.name,
                                   values=(str(target), TEXT["st_waiting"]))
        self._update_count()
        if skipped:
            self._report_image_books(skipped)

    def _report_image_books(self, skipped: list[Path]) -> None:
        """One notice for the whole batch, listed at the end — never one box per book."""
        from tkinter import messagebox
        shown = skipped[:12]
        names = "\n".join(book.name for book in shown)
        if len(skipped) > len(shown):
            names += "\n\n" + TEXT["image_more"].format(count=len(skipped) - len(shown))
        messagebox.showinfo(TEXT["image_title"],
                            TEXT["image_body"].format(count=len(skipped), names=names))

    def remove_selected(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        for key in self.queue_tree.selection():
            self.jobs.pop(key, None)
            self.queue_tree.delete(key)
        self._update_count()

    def clear_queue(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.jobs.clear()
        self.queue_tree.delete(*self.queue_tree.get_children())
        self._update_count()

    def _update_count(self, done: int = 0) -> None:
        total = len(self.jobs)
        self.progress.configure(maximum=max(1, total), value=done)
        self.count_var.set(f"{done} / {total}" if total else "")

    def _open_output(self, _event) -> None:  # type: ignore[no-untyped-def]
        import os
        selection = self.queue_tree.selection()
        if not selection:
            return
        _book, target = self.jobs.get(selection[0], (None, None))
        if target and target.exists() and hasattr(os, "startfile"):
            os.startfile(target)  # type: ignore[attr-defined]  # Windows only

    # -- the run
    def start(self) -> None:
        from tkinter import messagebox
        if self.worker and self.worker.is_alive():
            return
        if not self.jobs:
            messagebox.showinfo(TEXT["title"], TEXT["no_jobs"])
            return
        jobs = list(self.jobs.values())
        for key in self.jobs:
            self.queue_tree.set(key, "status", TEXT["st_waiting"])
        self.done = 0
        self._update_count()
        self.stop_flag.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.write_log(TEXT["queued"].format(count=len(jobs)))

        policy = OverwritePolicy(self._ask_from_worker)

        with_cover = bool(self.cover_var.get())  # read on this thread, not the worker's

        def work() -> None:
            tally = run(jobs, policy, lambda *event: self.events.put(event),
                        stop=self.stop_flag.is_set, with_cover=with_cover)
            self.events.put(("finished", None, None, tally))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def _ask_from_worker(self, dst: Path) -> str:
        """Called on the worker thread. Tk is single-threaded, so the dialog is
        handed to the main thread and the worker waits for the answer here."""
        answer: queue.Queue = queue.Queue(maxsize=1)
        self.events.put(("ask", dst, answer, ""))
        return answer.get()

    def _drain(self) -> None:
        """Main thread: apply whatever the worker has reported since last time."""
        try:
            while True:
                kind, book, dst, detail = self.events.get_nowait()
                self._apply(kind, book, dst, detail)
        except queue.Empty:
            pass
        self._tick = self.root.after(80, self._drain)

    def _apply(self, kind: str, book, dst, detail) -> None:  # type: ignore[no-untyped-def]
        if kind == "ask":
            self.pending_answer = dst  # the answer queue rides in the dst slot
            answer = _ask_overwrite(self.root, book)
            self.pending_answer = None
            dst.put(answer)
            return
        if kind == "finished":
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self.write_log(TEXT["finished"].format(**detail))
            return

        key = str(book)
        status = {"start": TEXT["st_working"], "ok": TEXT["st_done"],
                  "skip": TEXT["st_skipped"], "fail": TEXT["st_failed"]}.get(kind)
        if status and self.queue_tree.exists(key):
            self.queue_tree.set(key, "status", status)
            self.queue_tree.see(key)
        if kind == "start":
            self.write_log(f"{book.name} -> {dst.name}")
        elif kind == "ok":
            self.done += 1
            self._update_count(self.done)
            self.write_log(f"  OK  {dst.name}  {detail}")
        elif kind == "skip":
            self.done += 1
            self._update_count(self.done)
            self.write_log(f"  {TEXT['st_skipped']}  {dst.name}")
        elif kind == "fail":
            self.done += 1
            self._update_count(self.done)
            self.write_log(f"  {TEXT['st_failed']}  {book.name}: {detail}")
        elif kind == "stopped":
            self.write_log(TEXT["stop"])

    def write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        from tkinter import messagebox
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(TEXT["busy_title"], TEXT["busy"]):
                return
            self.stop_flag.set()
            if self.pending_answer is not None:
                self.pending_answer.put("quit")  # never leave the worker blocked
        self._remember()
        self.root.after_cancel(self._tick)  # else the pending tick fires into a dead window
        self.root.destroy()

    def _remember(self) -> None:
        _save_state({
            "source": str(self.root_dir) if self.root_dir else "",
            "output": self.output_var.get().strip(),
            "same": bool(self.same_var.get()),
            "mirror": bool(self.mirror_var.get()),
            "cover": bool(self.cover_var.get()),
            "lang": self.lang,
        })

    def _switch_language(self, _event=None) -> None:  # type: ignore[no-untyped-def]
        """Remember the choice and build the window again in the other language.

        Refused mid-conversion: the queue lives in this window, and tearing it down while a
        worker thread is writing files would leave the batch half-done with nothing on screen
        to say so. The picker snaps back so it never shows a language that is not in force.
        """
        from tkinter import messagebox

        wanted = "en" if self.lang_var.get() == TEXT["lang_en"] else "zh"
        if wanted == self.lang:
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(TEXT["busy_title"], TEXT["busy_lang"])
            self.lang_var.set(TEXT["lang_zh"] if self.lang == "zh" else TEXT["lang_en"])
            return
        self.lang = wanted
        self._remember()
        self.relaunch = True
        self.relaunch_source = self.root_dir
        self.relaunch_output = Path(self.output_var.get().strip() or ".")
        self.root.after_cancel(self._tick)
        self.root.destroy()


def _ask_overwrite(parent, dst: Path) -> str:  # type: ignore[no-untyped-def]
    """Modal yes / no / all / none. Closing it or Esc abandons the batch."""
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(parent)
    win.title(TEXT["overwrite_title"])
    win.transient(parent)
    win.resizable(False, False)
    choice = {"value": "quit"}

    ttk.Label(win, text=TEXT["overwrite_body"].format(path=dst), wraplength=440,
              justify="left").pack(padx=16, pady=(16, 10))
    row = ttk.Frame(win)
    row.pack(padx=16, pady=(0, 16))
    for index, (label, value) in enumerate(((TEXT["yes"], "yes"), (TEXT["no"], "no"),
                                            (TEXT["all"], "all"), (TEXT["none"], "none"))):
        button = ttk.Button(row, text=label, width=8,
                            command=lambda v=value: (choice.update(value=v), win.destroy()))
        button.pack(side="left", padx=4)
        if index == 0:
            button.focus_set()  # keyboard lands inside the dialog, so Esc reaches it
    win.bind("<Escape>", lambda _event: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.grab_set()
    win.focus_force()  # a question deserves the focus, and Esc needs it to land
    parent.wait_window(win)
    return choice["value"]


def run_gui(source: Path | None = None, output: Path | None = None) -> None:
    """The window, reopened once if the language is switched.

    Switching rebuilds rather than re-labelling: the widgets set their text once, when they
    are created, so a live switch would need every one of them registered somewhere and kept
    in step forever — and the one that got forgotten would sit there in the wrong language.
    Tearing the window down and building it again cannot be half-right. The paths carry over,
    and the switch is refused while a conversion is running.
    """
    import tkinter as tk

    while True:
        root = tk.Tk()
        gui = _Gui(root, source, output)
        root.mainloop()
        if not getattr(gui, "relaunch", False):
            return
        source, output = gui.relaunch_source, gui.relaunch_output


# ---------------------------------------------------------------- self-checks




if __name__ == "__main__":
    main()
