"""
shared/lang_utils.py
---------------------
كاشف لغة بسيط (عربي/إنجليزي/مختلط) بناءً على عدد الحروف، من غير أي
مكتبة خارجية. مستخدم عشان نظبط لغة رد الـ Summarizer على لغة سؤال
اليوزر بدل ما نسيبه يقلد لغة أول مصدر بيقرأه.
"""

import re

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# لو أقل نسبة كده من إجمالي الحروف بلغة معينة، منعتبرهاش "موجودة فعليًا"
# (بيحمينا من كلمة إنجليزية واحدة جوه سؤال عربي طويل، والعكس)
_MIN_PRESENCE_RATIO = 0.15


def detect_query_language(text: str) -> str:
    """
    يرجع "ar" لو عربي بس، "en" لو إنجليزي بس، أو "mixed" لو الاتنين
    موجودين بنسبة معتبرة مع بعض (يعني محتاجين نسأل اليوزر يفضل إيه).
    """
    arabic_count = len(_ARABIC_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    total = arabic_count + latin_count

    if total == 0:
        # مفيش حروف عربي ولا إنجليزي (أرقام/رموز بس) - افتراضي عربي
        return "ar"

    arabic_ratio = arabic_count / total
    latin_ratio = latin_count / total

    if arabic_ratio >= _MIN_PRESENCE_RATIO and latin_ratio >= _MIN_PRESENCE_RATIO:
        return "mixed"
    return "ar" if arabic_count >= latin_count else "en"
