"""Runbook search: BM25 over runbook sections.

Runbooks are keyword-dense (error strings, metric names), which lexical
retrieval handles well, and it needs no embedding quota.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "runbooks"
K1, B = 1.4, 0.75


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]


@dataclass
class Section:
    runbook: str
    title: str
    heading: str
    text: str


@lru_cache(maxsize=1)
def sections() -> list[Section]:
    out = []
    for f in sorted(DIR.glob("*.md")):
        lines = f.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ").strip()
        heading, buf = "Overview", []
        for line in lines[1:]:
            if line.startswith("## "):
                if buf:
                    out.append(Section(f.stem, title, heading, " ".join(buf).strip()))
                heading, buf = line[3:].strip(), []
            elif line.strip():
                buf.append(line.strip())
        if buf:
            out.append(Section(f.stem, title, heading, " ".join(buf).strip()))
    return out


@lru_cache(maxsize=1)
def _index():
    secs = sections()
    docs = [tokens(f"{s.title} {s.heading} {s.text}") for s in secs]
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    avg = sum(len(d) for d in docs) / len(docs)
    return secs, docs, df, avg


def search(query: str, k: int = 2) -> list[dict]:
    secs, docs, df, avg = _index()
    q = tokens(query)
    n = len(docs)
    scored = []
    for s, d in zip(secs, docs, strict=True):
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * len(d) / avg))
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [{"runbook": s.title, "section": s.heading, "text": s.text, "score": round(sc, 2)} for sc, s in scored[:k]]


def all_runbooks() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        out.append({"id": f.stem, "title": text.splitlines()[0].lstrip("# ").strip(), "markdown": text})
    return out
