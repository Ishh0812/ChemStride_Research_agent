"""China-specific research helpers: geo-block detection, source tiering,
per-field attribution and the run log.

Kept separate from research_agent_newest.py so the China workflow can evolve
without touching the shared country logic. Nothing here is China-only by
construction - block detection and attribution are generic - but the source
ladder and the block phrases are tuned for Chinese sites.

No paid APIs, no credentials: every source below is publicly reachable.
"""

import re
import threading
import time

# ==========================================
# GEO / ACCESS BLOCK DETECTION
# ==========================================

# Phrases that mean "we served you a wall, not the company page". Tianyancha
# returns the first few from outside mainland China; the rest cover the usual
# captcha/verification interstitials on Chinese business portals.
GEO_BLOCK_PATTERNS = (
    "当前所在地区暂不支持访问",
    "access is temporarily not supported in your current location",
    "current location",
    "当前ip",
    "current ip",
    "暂不支持访问",
    "该地区暂不支持",
    "访问受限",
    "请完成安全验证",
    "安全验证",
    "滑动验证",
    "人机验证",
    "verify you are human",
    "unusual traffic",
    "access denied",
    "403 forbidden",
)

# A real company page is substantial. A block/captcha interstitial is short,
# so a page that is BOTH short and contains a block phrase is a wall - the
# length test keeps a long genuine page that merely mentions "current IP"
# somewhere in its text from being discarded.
BLOCK_PAGE_MAX_CHARS = 2500

# Attempted at most once per run, then skipped. Tianyancha is the reason this
# exists; the others behave the same way from outside mainland China.
GEO_FRAGILE_HOSTS = ("tianyancha.com", "qcc.com", "qichacha.com", "aiqicha.com",
                     "gsxt.gov.cn", "11315.com")


def detect_geo_block(text, url=""):
    """True when this response is an access wall rather than company content."""
    if not text:
        return False
    low = text.lower()
    hit = any(pattern in low for pattern in GEO_BLOCK_PATTERNS)
    if not hit:
        return False
    # Long pages that merely mention a block phrase in passing are still real
    # content; only treat a short page as the wall itself.
    return len(text.strip()) <= BLOCK_PAGE_MAX_CHARS or "暂不支持访问" in low


# ==========================================
# BLOCKED-DOMAIN MEMORY (per research run)
# ==========================================

# Reachability is a property of the network path, not of one research run:
# if tianyancha.com walls us off, that is equally true for every run and for
# every worker thread. So this store is process-wide and lock-guarded rather
# than thread-local - a thread-local store would also be invisible to the
# crawler's worker threads, silently disabling the blocklist inside them.
# Entries expire so a host that was merely having a bad day gets retried.
_LOCK = threading.RLock()
_BLOCKED = {}      # host -> (reason, timestamp)
_HTTP_ONLY = {}    # host -> timestamp
_FAILURES = {}     # host -> consecutive failure count (per run)
_TTL_SECONDS = 15 * 60


def _fresh(entry_time):
    return (time.time() - entry_time) < _TTL_SECONDS


def _store():
    with _LOCK:
        return {h: reason for h, (reason, at) in _BLOCKED.items() if _fresh(at)}


def reset_blocked():
    """Call at the start of each research run.

    Clears the per-run failure counters. Block/HTTP-only knowledge is kept
    (it is network truth, and re-learning it costs another timeout) but ages
    out on its own via the TTL.
    """
    with _LOCK:
        _FAILURES.clear()


def _failures():
    return _FAILURES


def _http_only():
    with _LOCK:
        return {h for h, at in _HTTP_ONLY.items() if _fresh(at)}


def mark_http_only(url):
    """Remember that this host answers on :80 but not :443.

    Several mainland-hosted sites drop 443 from outside China. Once we know
    that, every later page on the host should skip straight to HTTP instead
    of paying the TLS timeout again - on an 8-page contact crawl that is the
    difference between ~8s and ~70s of dead waiting.
    """
    host = host_of(url)
    if host:
        with _LOCK:
            _HTTP_ONLY[host] = time.time()


def prefers_http(url):
    host = host_of(url)
    return bool(host) and any(host == h or host.endswith("." + h) for h in _http_only())


def note_failure(url, reason="unreachable", threshold=2):
    """Record a transient fetch failure; blocklist only on repetition.

    Blocklisting a host after a single exception is too harsh: one page on the
    company's OWN site timing out would otherwise disqualify the whole domain
    and abort the contact-page crawl. A definite signal (an access wall, or an
    anti-bot status code) still blocks immediately via mark_blocked().
    """
    host = host_of(url)
    if not host:
        return False
    counts = _failures()
    counts[host] = counts.get(host, 0) + 1
    if counts[host] >= threshold:
        mark_blocked(url, reason)
        return True
    return False


def mark_blocked(url, reason="geo_blocked"):
    host = host_of(url)
    if host:
        with _LOCK:
            _BLOCKED[host] = (reason, time.time())
    return reason


def is_blocked(url):
    """Has this host already served us a wall during this run?"""
    host = host_of(url)
    if not host:
        return False
    store = _store()
    return any(host == known or host.endswith("." + known) for known in store)


def blocked_report():
    """{host: reason} for everything skipped this run."""
    return dict(_store())


def host_of(url):
    match = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.IGNORECASE)
    return match.group(1).lower() if match else ""


# ==========================================
# SOURCE TIERING
# ==========================================

# Lower number = more trustworthy for contact details. Used to decide which
# competing value wins, and to keep news articles from ever being the primary
# source for a phone number or address.
TIER_OFFICIAL = 1        # the company's own domain
TIER_REGISTRY = 2        # government / official enterprise registry
TIER_PROFILE = 3         # verified business profiles (qcc, aiqicha, ...)
TIER_DIRECTORY = 4       # B2B directories already supported by the project
TIER_SNIPPET = 5         # search snippets - last resort
TIER_NEWS = 9            # never a primary source for contact data

REGISTRY_HOSTS = ("gsxt.gov.cn", "gov.cn", "creditchina.gov.cn", "11315.com")
PROFILE_HOSTS = ("qcc.com", "qichacha.com", "aiqicha.com", "tianyancha.com")
NEWS_HINTS = ("news", "article", "press", "media", "blog", "sohu.com", "sina.com",
              "163.com", "qq.com", "toutiao", "xinhuanet", "people.com.cn")


def source_tier(url, official_domain=""):
    """Rank a URL's trustworthiness for contact-detail extraction."""
    host = host_of(url)
    if not host:
        return TIER_SNIPPET
    if official_domain and (host == official_domain or host.endswith("." + official_domain)):
        return TIER_OFFICIAL
    if any(h in host for h in REGISTRY_HOSTS):
        return TIER_REGISTRY
    if any(h in host for h in PROFILE_HOSTS):
        return TIER_PROFILE
    if any(h in host or h in (url or "").lower() for h in NEWS_HINTS):
        return TIER_NEWS
    return TIER_DIRECTORY


def is_news_source(url):
    return source_tier(url) == TIER_NEWS


# ==========================================
# FREE CHINESE FALLBACK SOURCES
# ==========================================

# Ordered ladder used when the official site did not yield contact details.
# All are free to query through the existing SerpAPI web search - we search
# them via Google rather than hitting their (protected) internal APIs.
CN_FALLBACK_QUERIES = [
    # Government enterprise credit registry - the authoritative record.
    ("registry", '{name} 国家企业信用信息公示系统 注册地址 法定代表人'),
    # Verified business profiles.
    ("profile", '{name} 企查查 OR 爱企查 工商信息 注册地址 电话'),
    # Plain-language contact search, the way a person would type it.
    ("directory", '{name} 公司 地址 电话 邮箱 联系方式'),
]


# ==========================================
# PER-FIELD SOURCE ATTRIBUTION
# ==========================================

# parse_page_content() writes "\nSOURCE: <url>\n<page text>" into the corpus,
# so the corpus already records which page each span of text came from.
SOURCE_MARKER_RE = re.compile(r"\nSOURCE:\s*(\S+)\n")


def split_by_source(corpus):
    """[(url, text), ...] for a corpus built by parse_page_content()."""
    if not corpus:
        return []
    parts, last_end, current_url = [], 0, None
    for match in SOURCE_MARKER_RE.finditer(corpus):
        if current_url is not None:
            parts.append((current_url, corpus[last_end:match.start()]))
        elif match.start() > 0:
            parts.append((None, corpus[:match.start()]))
        current_url, last_end = match.group(1), match.end()
    parts.append((current_url, corpus[last_end:]))
    return [(u, t) for u, t in parts if t and t.strip()]


def attribute(value, corpus, official_domain=""):
    """Best source URL for an already-extracted value.

    Returns the most trustworthy page whose text actually contains the value,
    so a phone number that appears on both a news article and the company's
    own contact page is credited to the company.
    """
    if not value or not corpus:
        return None
    needle = re.sub(r"[\s\-().]", "", str(value))
    if not needle:
        return None

    best, best_tier = None, 99
    for url, text in split_by_source(corpus):
        if not url:
            continue
        flat = re.sub(r"[\s\-().]", "", text)
        if needle not in flat and str(value) not in text:
            continue
        tier = source_tier(url, official_domain)
        if tier < best_tier:
            best, best_tier = url, tier
    return best


# ==========================================
# ADDRESS CLEANUP
# ==========================================

# Where a scraped address ends and the next section of the page begins.
# Company-profile pages run "<address>查看地图 经营范围：..." together, so
# without this the address swallows the business scope that follows it.
ADDRESS_STOP_MARKERS = (
    "查看地图", "地图", "经营范围", "许可项目", "一般项目", "附近公司", "附近企业",
    "统一社会信用代码", "成立日期", "成立时间", "注册资本", "法定代表人", "登记状态",
    "所属行业", "企业类型", "营业期限", "更多", "展开", "简介", "官网", "邮箱",
    "电话", "客服", "版权", "备案",
)


def trim_cn_address(text):
    """Cut a scraped Chinese address back to just the address."""
    if not text:
        return text
    cleaned = re.sub(r"\s+", " ", text).strip()
    cut = len(cleaned)
    for marker in ADDRESS_STOP_MARKERS:
        at = cleaned.find(marker)
        # Require a plausible address before the marker, so a string that
        # merely starts with one is not trimmed away to nothing.
        if 6 <= at < cut:
            cut = at
    cleaned = cleaned[:cut]
    # Search snippets end in an ellipsis that is not part of the address.
    cleaned = re.sub(r"[.…]{2,}\s*$", "", cleaned)
    return cleaned.strip(" \t,，。;；·、-") or None


# ==========================================
# PHONE LABELLING / DEDUPE
# ==========================================

FAX_HINTS = ("传真", "fax")
MOBILE_HINTS = ("手机", "移动电话", "mobile", "cell")
OFFICE_HINTS = ("电话", "телефон", "tel", "phone", "座机", "热线", "office")


def label_phone(raw_number, corpus, window=60):
    """office / mobile / fax, from the wording next to the number.

    Returns None when nothing nearby says which it is - guessing a label is
    worse than leaving it unlabelled.
    """
    if not raw_number or not corpus:
        return None
    digits = re.sub(r"\D", "", str(raw_number))[-8:]
    if len(digits) < 6:
        return None

    for match in re.finditer(r"\d[\d\s\-().]{5,}", corpus):
        if digits not in re.sub(r"\D", "", match.group(0)):
            continue
        before = corpus[max(0, match.start() - window):match.start()].lower()
        # Use the hint NEAREST the number. A fixed priority order would let
        # the previous line's "传真：" label claim the mobile number that
        # follows it, since both fall inside the lookback window.
        nearest, nearest_at = None, -1
        for label, hints in (("fax", FAX_HINTS), ("mobile", MOBILE_HINTS), ("office", OFFICE_HINTS)):
            for hint in hints:
                at = before.rfind(hint)
                if at > nearest_at:
                    nearest, nearest_at = label, at
        if nearest:
            return nearest
    return None


def dedupe_entries(entries):
    """Collapse duplicate contact values, keeping the best-attributed one."""
    seen, out = {}, []
    for entry in entries:
        key = re.sub(r"[\s\-().]", "", str(entry.get("value", ""))).lower()
        if not key:
            continue
        if key in seen:
            existing = seen[key]
            if not existing.get("source") and entry.get("source"):
                existing["source"] = entry["source"]
            if not existing.get("label") and entry.get("label"):
                existing["label"] = entry["label"]
            continue
        seen[key] = entry
        out.append(entry)
    return out


# ==========================================
# RESEARCH LOG
# ==========================================

class ResearchLog:
    """The ✓/✗ trace shown alongside the results."""

    def __init__(self, title="China Research"):
        self.title = title
        self.entries = []

    def ok(self, message):
        self.entries.append({"status": "ok", "message": message})
        print(f"   ✓ {message}")

    def fail(self, message):
        self.entries.append({"status": "fail", "message": message})
        print(f"   ✗ {message}")

    def info(self, message):
        self.entries.append({"status": "info", "message": message})
        print(f"   · {message}")

    def as_dict(self):
        return {"title": self.title, "entries": self.entries}

    def as_text(self):
        icon = {"ok": "✓", "fail": "✗", "info": "·"}
        lines = [f"[{self.title}]"]
        lines += [f"{icon[e['status']]} {e['message']}" for e in self.entries]
        return "\n".join(lines)
