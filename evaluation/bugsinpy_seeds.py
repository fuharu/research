# -*- coding: utf-8 -*-
"""
Warm シード定義（兄弟＝同種だが同一でない成功事例）。
run_bugsinpy_memory.py が SEED_KEY="proj:bug" で引く。

構成方針（artifact 回避）：
  donor バグ（別の実バグ）の【実際の失敗テスト出力】を error_log に、
  【実際の修正(diff該当箇所)】を fix_code に入れる。＝過去に実際に直した兄弟ケース。

black の #4 と #19 は兄弟：どちらも EmptyLineTracker の「空行を挿入してしまう」エッジケース。
  - #4 : ファイル先頭に空行を入れてしまう（previous_line is None を考慮していない）
  - #19: デコレータ用コメントの間に空行を入れてしまう（is_comment を考慮していない）
条件は別なので「答えのコピー」ではなく、技法（空行ロジックでエッジケースを早期 return）の転移。
"""

# ---- donor #4 の実データ（target #19 用） -----------------------------------
_DONOR4_ERR = (
    "AssertionError: 'print(\"hello, world\")\\n' != '\\n\\nprint(\"hello, world\")\\n'\n"
    "black が整形時にファイル先頭へ余分な空行を挿入してしまう "
    "(tests/test_black.py test_beginning_backslash で失敗)。"
)
_DONOR4_FIX = (
    "EmptyLineTracker.maybe_empty_lines を修正：先頭行(previous_line is None)では\n"
    "空行を入れないようにする。\n"
    "        before, after = self._maybe_empty_lines(current_line)\n"
    "        before = (\n"
    "            # Black should not insert empty lines at the beginning of the file\n"
    "            0\n"
    "            if self.previous_line is None\n"
    "            else before - self.previous_after\n"
    "        )\n"
)

# ---- donor #19 の実データ（target #4 用） ----------------------------------
_DONOR19_ERR = (
    "AssertionError: デコレータ用コメント(@property の前の # TODO 等)の間に\n"
    "余分な空行が挿入される。期待値と実際で空行数が一致せず失敗 "
    "(tests/test_black.py のデコレータ周りのテスト)。"
)
_DONOR19_FIX = (
    "EmptyLineTracker._maybe_empty_lines を修正：デコレータかつ直前がコメントなら\n"
    "空行を入れずに早期 return する。\n"
    "            if is_decorator and self.previous_line and self.previous_line.is_comment:\n"
    "                # Don't insert empty lines between decorator comments.\n"
    "                return 0, 0\n"
)

SEEDS = {
    "black:19": {"error_log": _DONOR4_ERR,  "fix_code": _DONOR4_FIX},
    "black:4":  {"error_log": _DONOR19_ERR, "fix_code": _DONOR19_FIX},
}
