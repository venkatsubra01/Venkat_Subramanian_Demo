"""Minimal text-only PDF writer (standard Helvetica fonts, WinAnsi encoding, US Letter).

Enough for a local, uncompressed summary document; no images, embedded fonts or links.
"""

import textwrap

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 54
BOTTOM = 64
AVERAGE_CHAR_WIDTH = 0.52  # Helvetica, as a fraction of the font size; used for wrapping.


def _pdf_string(text: str) -> bytes:
    cleaned = "".join(ch if ch >= " " else " " for ch in text)
    raw = cleaned.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class TextPdf:
    def __init__(self, footer: str) -> None:
        self._footer = footer
        self._pages: list[list[bytes]] = []
        self._y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self._pages.append([])
        self._y = PAGE_HEIGHT - MARGIN

    def _ensure_space(self, height: float) -> None:
        if self._y - height < BOTTOM:
            self._new_page()

    def _draw(self, text: str, x: float, y: float, size: float, bold: bool) -> bytes:
        font = b"/F2" if bold else b"/F1"
        return b"BT %s %.1f Tf %.1f %.1f Td %s Tj ET" % (font, size, x, y, _pdf_string(text))

    def text(self, text: str, size: float = 10, bold: bool = False, indent: float = 0) -> None:
        width_chars = max(20, int((PAGE_WIDTH - 2 * MARGIN - indent) / (size * AVERAGE_CHAR_WIDTH)))
        leading = size * 1.35
        for paragraph in text.splitlines() or [""]:
            for line in textwrap.wrap(paragraph, width_chars, break_long_words=True) or [""]:
                self._ensure_space(leading)
                self._y -= leading
                self._pages[-1].append(self._draw(line, MARGIN + indent, self._y, size, bold))

    def heading(self, text: str) -> None:
        self._ensure_space(40)
        self.space(8)
        self.text(text, size=12, bold=True)
        self.space(2)

    def space(self, height: float = 6) -> None:
        self._y -= height

    def render(self) -> bytes:
        objects: list[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"",  # pages tree, filled below
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
        page_ids: list[int] = []
        total = len(self._pages)
        for number, operations in enumerate(self._pages, start=1):
            footer = f"{self._footer}  -  page {number} of {total}"
            stream = b"\n".join([*operations, self._draw(footer, MARGIN, 36, 8, False)])
            objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
            content_id = len(objects)
            objects.append(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                % (PAGE_WIDTH, PAGE_HEIGHT, content_id)
            )
            page_ids.append(len(objects))
        kids = b" ".join(b"%d 0 R" % page_id for page_id in page_ids)
        objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, total)

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for index, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (index, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
        return bytes(out)
