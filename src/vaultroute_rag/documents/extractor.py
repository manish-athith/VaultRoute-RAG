import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


class DocumentExtractionError(ValueError):
    """Raised when an uploaded file cannot be safely converted to text."""


@dataclass(frozen=True)
class ExtractedText:
    text: str
    filename: str
    media_type: str


class _VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        elif tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


class DocumentTextExtractor:
    """Extract text from a small, explicit allow-list of document formats."""

    _media_types = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        return tuple(self._media_types)

    def extract(self, filename: str, data: bytes) -> ExtractedText:
        safe_filename = Path(filename.replace("\\", "/")).name.strip()
        suffix = Path(safe_filename).suffix.lower()
        if not safe_filename or suffix not in self._media_types:
            allowed = ", ".join(self.supported_extensions)
            raise DocumentExtractionError(f"Unsupported file type; allowed: {allowed}")
        if not data:
            raise DocumentExtractionError("Uploaded document is empty")

        if suffix in {".txt", ".md"}:
            text = self._decode_text(data)
        elif suffix in {".html", ".htm"}:
            parser = _VisibleHtmlParser()
            parser.feed(self._decode_text(data))
            text = " ".join(parser.parts)
        elif suffix == ".pdf":
            text = self._extract_pdf(data)
        else:
            text = self._extract_docx(data)

        normalized = self._normalize(text)
        if not normalized:
            raise DocumentExtractionError("No readable text was found in the document")
        return ExtractedText(
            text=normalized,
            filename=safe_filename,
            media_type=self._media_types[suffix],
        )

    @staticmethod
    def _decode_text(data: bytes) -> str:
        if b"\x00" in data:
            raise DocumentExtractionError("Text document contains binary data")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentExtractionError("Text documents must use UTF-8 encoding") from exc

    @staticmethod
    def _extract_pdf(data: bytes) -> str:
        if not data.startswith(b"%PDF"):
            raise DocumentExtractionError("The file extension is PDF but its content is not")
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise DocumentExtractionError("Encrypted PDFs are not supported")
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except DocumentExtractionError:
            raise
        except Exception as exc:
            raise DocumentExtractionError("The PDF could not be read") from exc

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        if not data.startswith(b"PK"):
            raise DocumentExtractionError("The file extension is DOCX but its content is not")
        try:
            document = DocxDocument(BytesIO(data))
            return "\n\n".join(paragraph.text for paragraph in document.paragraphs)
        except Exception as exc:
            raise DocumentExtractionError("The DOCX file could not be read") from exc

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.rstrip() for line in text.splitlines())
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
