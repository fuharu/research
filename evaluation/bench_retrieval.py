# -*- coding: utf-8 -*-
"""
localization 候補の retrieval（lexical top-K, 依存追加なし）。
失敗テスト/トレースバックのテキストを query とし、リポ内 .py を
トークン重なりでスコアして上位K件を候補に返す。Warm/Cold 共通で使う。
"""
import os, re

EXCLUDE = ("/.git/", "/env/", "/test/", "/tests/", "/docs/", "/.eggs/", "/build/")

def _toks(s):
    return [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if len(t) >= 3]

def list_py(root):
    out = []
    for dp, _, fs in os.walk(root):
        d = dp + "/"
        if any(e in d for e in EXCLUDE):
            continue
        for f in fs:
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return out

def retrieve(root, query, k=12, max_lines=400):
    """top-K候補パスを返す。max_lines: これ以下の行数のファイルを優先（全体書換可能なもの）。"""
    q = set(_toks(query))
    scored = []
    for fp in list_py(root):
        try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        ft = set(_toks(txt))
        score = len(q & ft) + 3 * len(q & set(_toks(os.path.basename(fp))))
        nlines = txt.count("\n") + 1
        scored.append((score, nlines, fp))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(fp, nl) for sc, nl, fp in scored[:k]]
