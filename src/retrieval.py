"""BM25 retrieval over the runbook corpus."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from rank_bm25 import BM25Okapi


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class Runbook:
    runbook_id: str
    title: str
    category: Optional[str]
    text: str


@dataclass
class RetrievalHit:
    runbook: Runbook
    score: float


class RunbookIndex:
    """Loads markdown runbooks from a directory and builds a BM25 index over them."""

    def __init__(self, runbook_dir: str | os.PathLike):
        self.runbook_dir = Path(runbook_dir)
        self.runbooks: List[Runbook] = self._load_runbooks()
        if not self.runbooks:
            raise ValueError(f"No runbooks found in {self.runbook_dir}")
        tokenized_corpus = [_tokenize(rb.text) for rb in self.runbooks]
        self._bm25 = BM25Okapi(tokenized_corpus)

    def _load_runbooks(self) -> List[Runbook]:
        runbooks = []
        for path in sorted(self.runbook_dir.glob("*.md")):
            text = path.read_text()
            title = self._extract_title(text) or path.stem
            category = self._extract_category(text)
            runbooks.append(
                Runbook(
                    runbook_id=path.stem,
                    title=title,
                    category=category,
                    text=text,
                )
            )
        return runbooks

    @staticmethod
    def _extract_title(text: str) -> Optional[str]:
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return None

    @staticmethod
    def _extract_category(text: str) -> Optional[str]:
        match = re.search(r"\*\*Category:\*\*\s*(\w+)", text)
        return match.group(1).strip().lower() if match else None

    def search(self, query: str, k: int = 3) -> List[RetrievalHit]:
        tokenized_query = _tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        ranked = sorted(
            zip(self.runbooks, scores), key=lambda pair: pair[1], reverse=True
        )
        return [RetrievalHit(runbook=rb, score=float(score)) for rb, score in ranked[:k]]
