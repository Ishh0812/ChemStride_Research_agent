"""
Country-aware B2B research agent.

Key differences vs v1:
  * Country is a MANDATORY input. It drives the Google locale (gl/hl), the
    dial code, the phone grammar, the B2B portal set and the "is this really
    their website" test. No more Chinese companies resolving to a Canadian site.
  * Per-country portal routing => portals are only queried for the country you
    picked, and only when Google failed to give a website. Saves SerpAPI units.
  * Chinese support: Chinese-language queries, Chinese phone/landline grammar,
    WeChat (微信) extraction, and Chinese address -> English translation.
  * On-disk cache so re-running the same company costs 0 units.
"""

import os
import re
import json
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from dotenv import load_dotenv
from serpapi import GoogleSearch
import requests
from bs4 import BeautifulSoup

import china_sources

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_API_KEY")

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".research_cache.json")
CACHE_TTL_DAYS = 14
CACHE_VERSION = 6  # bumped: adds evidence/research_log + China geo-block handling

# Optional dependencies. Everything degrades gracefully if they are missing.
try:
    from deep_translator import GoogleTranslator  # pip install deep-translator
except Exception:
    GoogleTranslator = None

try:
    from pypinyin import lazy_pinyin  # pip install pypinyin
except Exception:
    lazy_pinyin = None


# ==========================================
# SERPAPI USAGE METER
# ==========================================

class Usage:
    calls = 0

    @classmethod
    def bump(cls, label):
        cls.calls += 1
        print(f"   [serpapi #{cls.calls}] {label}")


def serp_search(params, label):
    Usage.bump(label)
    params = dict(params)
    params["api_key"] = SERPAPI_KEY
    try:
        return GoogleSearch(params).get_dict().get("organic_results", []) or []
    except Exception as exc:
        print(f"   ⚠️ SerpAPI error: {exc}")
        return []


# ==========================================
# COUNTRY PROFILES
# ==========================================

# Portals are searched ONLY for the selected country.
COUNTRY_PROFILES = {
    "IN": {
        "name": "India",
        "dial_code": "91",
        "gl": "in",
        "hl": "en",
        "google_domain": "google.co.in",
        "query_lang": "en",
        # mobile (10 digits, 6-9 lead) + landline (STD 2-4 + 6-8 digits)
        "phone_patterns": [r"[6-9]\d{9}", r"(11|22|33|44|20|40|79|80)\d{8}", r"\d{3,4}\d{6,7}"],
        "nsn_len": (10, 11),
        "tld_bonus": [".in", ".co.in", ".net.in"],
        "portals": [
            "site:indiamart.com/company",
            "site:indiamart.com/proddetail",
            "site:zaubacorp.com/company",
            "site:justdial.com",
            "site:tradeindia.com",
            "site:exportersindia.com",
            "site:cphi-online.com/company",
        ],
        "portal_hosts": [
            "indiamart.com", "zaubacorp.com", "justdial.com",
            "tradeindia.com", "exportersindia.com", "cphi-online.com",
        ],
        "messenger": "whatsapp",
        "cities": [
            "Mumbai", "Navi Mumbai", "Thane", "Delhi", "New Delhi", "Noida", "Gurugram",
            "Gurgaon", "Faridabad", "Ahmedabad", "Vadodara", "Surat", "Rajkot", "Ankleshwar",
            "Vapi", "Bharuch", "Pune", "Nashik", "Nagpur", "Aurangabad", "Bengaluru",
            "Bangalore", "Chennai", "Coimbatore", "Hyderabad", "Secunderabad", "Kolkata",
            "Indore", "Bhopal", "Jaipur", "Ludhiana", "Chandigarh", "Baddi", "Kanpur",
            "Lucknow", "Visakhapatnam", "Kochi", "Cochin", "Daman", "Silvassa", "Halol",
        ],
    },
    "CN": {
        "name": "China",
        "dial_code": "86",
        "gl": "cn",
        "hl": "zh-cn",
        "google_domain": "google.com",
        "query_lang": "zh",
        # mobile 1[3-9]xxxxxxxxx ; landline area(2-3) + 7-8
        "phone_patterns": [r"1[3-9]\d{9}", r"(10|2[0-9])\d{8}", r"[3-9]\d{2}\d{7,8}"],
        "nsn_len": (10, 12),
        "tld_bonus": [".cn", ".com.cn", ".net.cn"],
        # Searched in the order below, in small batches (see
        # search_country_portals) - Google returns poor results when too many
        # site: operators are OR'd into a single query. Batch 1 is the
        # chemical/registry set that already worked; batches 2-3 are the
        # export-facing B2B directories where Chinese suppliers publish
        # contact details for overseas buyers.
        "portals": [
            "site:made-in-china.com",
            "site:chemicalbook.com",
            "site:guidechem.com",
            "site:echemi.com",
            "site:molbase.com",
            "site:lookchem.com",
            "site:chemnet.com",
            "site:qcc.com",

            "site:alibaba.com",
            "site:globalsources.com",
            "site:tradekey.com",
            "site:go4worldbusiness.com",
            "site:ec21.com",
            "site:ecplaza.net",

            "site:b2bmanufactures.com",
            "site:etradeasia.com",
            "site:tradeford.com",
            "site:b2bmit.com",
            "site:hisupplier.com",
            "site:taiwantrade.com",
            "site:buykorea.org",
            "site:koreatradeworld.com",
            "site:indotrade.com",
        ],
        "portal_hosts": [
            "made-in-china.com", "chemicalbook.com", "guidechem.com", "echemi.com",
            "molbase.com", "lookchem.com", "chemnet.com", "qcc.com", "1688.com",
            "hc360.com", "gongchang.com", "tianyancha.com",
            "alibaba.com", "globalsources.com", "tradekey.com", "go4worldbusiness.com",
            "ec21.com", "ecplaza.net", "b2bmanufactures.com", "etradeasia.com",
            "tradeford.com", "b2bmit.com", "hisupplier.com", "taiwantrade.com",
            "buykorea.org", "koreatradeworld.com", "indotrade.com",
        ],
        "messenger": "wechat",
        "cities": [
            "Shanghai", "Beijing", "Tianjin", "Chongqing", "Shenzhen", "Guangzhou",
            "Dongguan", "Foshan", "Zhuhai", "Shantou", "Hangzhou", "Ningbo", "Wenzhou",
            "Shaoxing", "Jiaxing", "Taizhou", "Suzhou", "Wuxi", "Changzhou", "Nanjing",
            "Nantong", "Yangzhou", "Zhenjiang", "Xuzhou", "Lianyungang", "Qingdao",
            "Jinan", "Zibo", "Weifang", "Yantai", "Weihai", "Dongying", "Linyi",
            "Zhengzhou", "Luoyang", "Wuhan", "Yichang", "Changsha", "Nanchang",
            "Hefei", "Fuzhou", "Xiamen", "Quanzhou", "Shijiazhuang", "Handan",
            "Cangzhou", "Taiyuan", "Xi'an", "Lanzhou", "Chengdu", "Kunming",
            "Guiyang", "Nanning", "Shenyang", "Dalian", "Anshan", "Changchun",
            "Harbin", "Hohhot", "Urumqi", "Haikou", "Yinchuan", "Xining",
        ],
    },
    "US": {
        "name": "United States",
        "dial_code": "1",
        "gl": "us", "hl": "en", "google_domain": "google.com", "query_lang": "en",
        "phone_patterns": [r"[2-9]\d{2}[2-9]\d{6}"],
        "nsn_len": (10, 10),
        "tld_bonus": [".com", ".us"],
        "portals": ["site:thomasnet.com", "site:manta.com", "site:bloomberg.com/profile"],
        "portal_hosts": ["thomasnet.com", "manta.com", "bloomberg.com"],
        "messenger": "whatsapp",
        "cities": ["New York", "Houston", "Chicago", "Los Angeles", "Philadelphia",
                   "Dallas", "Atlanta", "Charlotte", "Newark", "Cleveland", "Detroit"],
    },
    "DE": {
        "name": "Germany",
        "dial_code": "49",
        "gl": "de", "hl": "de", "google_domain": "google.de", "query_lang": "de",
        "phone_patterns": [r"\d{3,5}\d{5,8}"],
        "nsn_len": (9, 12),
        "tld_bonus": [".de"],
        "portals": ["site:wlw.de", "site:northdata.de", "site:chemeurope.com"],
        "portal_hosts": ["wlw.de", "northdata.de", "chemeurope.com"],
        "messenger": "whatsapp",
        "cities": ["Frankfurt", "Hamburg", "Munich", "Cologne", "Dusseldorf",
                   "Leverkusen", "Ludwigshafen", "Berlin", "Stuttgart", "Essen"],
    },
    "AE": {
        "name": "United Arab Emirates",
        "dial_code": "971",
        "gl": "ae", "hl": "en", "google_domain": "google.ae", "query_lang": "en",
        "phone_patterns": [r"5[0-9]\d{7}", r"[2-9]\d{7}"],
        "nsn_len": (8, 9),
        "tld_bonus": [".ae"],
        "portals": ["site:yellowpages-uae.com", "site:uaecontact.com"],
        "portal_hosts": ["yellowpages-uae.com", "uaecontact.com"],
        "messenger": "whatsapp",
        "cities": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah"],
    },
    "VN": {
        "name": "Vietnam",
        "dial_code": "84",
        "gl": "vn", "hl": "vi", "google_domain": "google.com.vn", "query_lang": "en",
        "phone_patterns": [r"[35789]\d{8}", r"\d{9,10}"],
        "nsn_len": (9, 10),
        "tld_bonus": [".vn", ".com.vn"],
        "portals": ["site:yellowpages.vn", "site:vietnamyellowpages.vn"],
        "portal_hosts": ["yellowpages.vn", "vietnamyellowpages.vn"],
        "messenger": "whatsapp",
        "cities": ["Ho Chi Minh City", "Hanoi", "Da Nang", "Hai Phong", "Binh Duong"],
    },
    "KR": {
        "name": "South Korea",
        "dial_code": "82",
        "gl": "kr", "hl": "ko", "google_domain": "google.co.kr", "query_lang": "en",
        "phone_patterns": [r"10\d{8}", r"\d{2,3}\d{7,8}"],
        "nsn_len": (9, 11),
        "tld_bonus": [".kr", ".co.kr"],
        "portals": ["site:kompass.com", "site:ec21.com"],
        "portal_hosts": ["kompass.com", "ec21.com"],
        "messenger": "whatsapp",
        "cities": ["Seoul", "Busan", "Incheon", "Ulsan", "Daejeon", "Yeosu"],
    },
    "JP": {
        "name": "Japan",
        "dial_code": "81",
        "gl": "jp", "hl": "ja", "google_domain": "google.co.jp", "query_lang": "en",
        "phone_patterns": [r"[789]0\d{8}", r"\d{1,4}\d{6,8}"],
        "nsn_len": (9, 10),
        "tld_bonus": [".jp", ".co.jp"],
        "portals": ["site:kompass.com", "site:jpubb.com"],
        "portal_hosts": ["kompass.com", "jpubb.com"],
        "messenger": "whatsapp",
        "cities": ["Tokyo", "Osaka", "Nagoya", "Yokohama", "Kobe", "Kawasaki"],
    },
}

DEFAULT_COUNTRY = "IN"

# Never classified as an official company website, in any country.
BLOCKED_WEBSITE_DOMAINS = {
    "indiamart.com", "tradeindia.com", "justdial.com", "zaubacorp.com",
    "exportersindia.com", "cphi-online.com", "tofler.in", "company360.in",
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "youtube.com", "go4worldbusiness.com", "made-in-china.com", "alibaba.com",
    "1688.com", "hc360.com", "gongchang.com", "chemicalbook.com", "guidechem.com",
    "echemi.com", "molbase.com", "lookchem.com", "chemnet.com", "qcc.com",
    "tianyancha.com", "aiqicha.com", "baidu.com", "sohu.com", "weibo.com",
    "thomasnet.com", "manta.com", "kompass.com", "ec21.com", "wlw.de",
    "northdata.de", "chemeurope.com", "rbi.org.in", "sebi.gov.in", "mca.gov.in",
    "nseindia.com", "bseindia.com", "pinterest.com", "tracxn.com",
    "crunchbase.com", "bloomberg.com", "wikipedia.org", "zoominfo.com",
    "dnb.com", "yellowpages.com", "glassdoor.com", "indeed.com",
    # B2B directories: useful as DATA sources (see portal_hosts), but a
    # supplier's storefront on one of them is never the company's own site.
    "globalsources.com", "tradekey.com", "b2bmanufactures.com", "etradeasia.com",
    "tradeford.com", "b2bmit.com", "ecplaza.net", "hisupplier.com",
    "taiwantrade.com", "buykorea.org", "koreatradeworld.com", "indotrade.com",
}

LEGAL_SUFFIXES = {
    "private", "limited", "company", "corporation", "corp", "industries",
    "pvt", "ltd", "llp", "inc", "enterprises", "group", "holdings", "co",
    "gmbh", "ag", "sa", "bv", "srl", "plc", "llc", "trading", "international",
    "technology", "technologies", "chemical", "chemicals",
}

# Words that say what a company DOES, not which company it IS. A domain that
# matches only these is an industry portal or directory - asiamachinery.net
# scored as the "official website" of "Zhengzhou Yufeng Heavy Machinery"
# purely because "machinery" is a substring of it - so a distinctive token
# (the actual name: "zhengzhou", "yufeng") has to match as well.
GENERIC_INDUSTRY_WORDS = {
    "machinery", "machine", "machines", "heavy", "industry", "industrial",
    "equipment", "steel", "metal", "metals", "plastic", "plastics", "rubber",
    "textile", "textiles", "packaging", "electric", "electrical", "electronic",
    "electronics", "energy", "power", "solar", "pharma", "pharmaceutical",
    "pharmaceuticals", "biotech", "medical", "food", "agro", "auto",
    "automotive", "motor", "tools", "hardware", "import", "export", "imports",
    "exports", "supply", "supplies", "supplier", "suppliers", "manufacture",
    "manufacturing", "manufacturer", "manufacturers", "products", "product",
    "material", "materials", "global", "asia", "asian", "china", "national",
    "international", "worldwide", "trade", "trading",
}

GENERIC_NAMES = {
    "home contact us", "contact us", "about us", "investor", "investors",
    "customer care", "customer service", "supplier", "supplier mr",
    "mr", "ms", "mrs", "codes", "menu", "home", "contact", "support team",
    "sales manager", "director", "manager", "admin", "vendor", "general manager",
    "authorized signatory", "key management personnel",
}

MARKETING_WORDS = {
    "structured", "protect", "protecting", "protected", "committed",
    "helping", "quality", "trusted", "leading", "innovative", "solutions",
    "excellence", "delivering", "empowering", "building", "creating",
    "driven", "focused", "dedicated", "reliable", "sustainable", "future", "growth",
}

STOP_WORDS = {
    "and", "or", "the", "in", "on", "at", "by", "for", "with", "about",
    "handled", "handling", "services", "solutions", "products", "team",
    "management", "board", "regulatory", "documentation", "compliance",
    "quality", "assurance", "operations", "business", "global", "office",
    "pvt", "ltd", "limited", "company", "chemstride", "stride", "chemical",
}

# Free mailboxes that ARE legitimate business addresses in China.
CN_FREEMAIL = {"163.com", "126.com", "qq.com", "sina.com", "sina.cn", "yeah.net",
               "aliyun.com", "139.com", "vip.163.com", "foxmail.com", "21cn.com"}

# Known bilingual aliases improve Chinese official-site discovery.
CN_COMPANY_ALIASES = {
    "sinopec": ["中国石化", "中国石油化工集团有限公司", "中国石油化工股份有限公司", "Sinopec"],
    "sinopec corp": ["中国石化", "中国石油化工股份有限公司", "Sinopec Corp", "Sinopec"],
    "china petroleum chemical corporation": ["中国石化", "中国石油化工股份有限公司", "Sinopec Corp"],
}
CN_OFFICIAL_SIGNAL_WORDS = ("官网", "官方网站", "联系我们", "联系方式", "公司地址", "注册地址", "办公地址", "联系电话", "联系地址", "电话", "邮箱", "企业简介")
CN_NEWS_WORDS = ("新闻", "资讯", "消息", "报道", "评论", "媒体", "news", "article", "newsroom", "press")

# Strong domain hints for major Chinese companies.  When a known company has a
# verified official domain, that domain always beats news sites, portals and
# similarly named third-party domains.
CN_OFFICIAL_DOMAIN_HINTS = {
    "sinopec": ["sinopec.com"],
    "sinopec corp": ["sinopec.com"],
    "china petroleum chemical corporation": ["sinopec.com"],
    "中国石化": ["sinopec.com"],
    "中国石油化工集团有限公司": ["sinopec.com"],
    "中国石油化工股份有限公司": ["sinopec.com"],
}

CN_OFFICIAL_CANONICAL_URLS = {
    "sinopec": "https://www.sinopec.com",
    "sinopec corp": "https://www.sinopec.com",
    "china petroleum chemical corporation": "https://www.sinopec.com",
    "中国石化": "https://www.sinopec.com",
    "中国石油化工集团有限公司": "https://www.sinopec.com",
    "中国石油化工股份有限公司": "https://www.sinopec.com",
}


# ==========================================
# BASIC HELPERS
# ==========================================

CJK_RE = re.compile(r"[一-鿿]")


def has_cjk(text):
    return bool(CJK_RE.search(text or ""))


def normalize_name(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def name_tokens(company_name):
    """Distinctive latin tokens of a company name (legal suffixes dropped)."""
    return [
        w for w in normalize_name(company_name).split()
        if len(w) >= 4 and w not in LEGAL_SUFFIXES
    ]


def source_domain(url):
    match = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.IGNORECASE)
    return match.group(1).lower() if match else ""


def domain_matches(domain, candidate):
    """True only on an exact host match or a real subdomain of it.

    Substring matching is wrong here: "x.com" is inside "synapex.com".
    """
    return domain == candidate or domain.endswith("." + candidate)


def is_blocked_domain(url):
    domain = source_domain(url)
    if not domain:
        return True
    return any(domain_matches(domain, b) for b in BLOCKED_WEBSITE_DOMAINS)


def decode_cf_email(cf_hex):
    try:
        k = int(cf_hex[:2], 16)
        return "".join(chr(int(cf_hex[i:i + 2], 16) ^ k) for i in range(2, len(cf_hex), 2))
    except Exception:
        return ""


def resolve_country(code):
    if not code:
        return DEFAULT_COUNTRY
    code = code.strip().upper()
    if code in COUNTRY_PROFILES:
        return code
    for key, prof in COUNTRY_PROFILES.items():
        if prof["name"].upper() == code:
            return key
    return DEFAULT_COUNTRY


def empty_result(company_name, country):
    profile = COUNTRY_PROFILES[country]
    return {
        "company": company_name,
        "country": profile["name"],
        "country_code": country,
        "dial_code": "+" + profile["dial_code"],
        "website": None,
        "email": None,
        "phone": None,
        "whatsapp": None,
        "wechat": None,
        "preferred_messenger": None,
        "contact_person": None,
        "designation": None,
        "location": None,
        "address": None,
        "address_original": None,
        "industry": None,
        "products": [],
        "sources": [],
        "linkedin": {
            "company_page": None,
            "role_searched": None,
            "fallback_used": False,
            "people": [],
            "note": None,
        },
        # Additive: per-field source attribution. The flat fields above keep
        # their existing shape so nothing downstream (frontend included) has
        # to change; this block says WHERE each value came from.
        "evidence": {
            "company_name": company_name,
            "website": None,
            "phone": [],
            "email": [],
            "address": {"original": None, "english": None, "source": None},
            "legal_representative": None,
            "main_business": None,
            "key_personnel": [],
            "blocked_sources": {},
        },
        "research_log": None,
    }


# ==========================================
# CACHE  (re-running a company costs 0 SerpAPI units)
# ==========================================

def _cache_key(company_name, country):
    raw = f"v{CACHE_VERSION}|{country}|{normalize_name(company_name) or company_name}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def cache_load(company_name, country):
    if os.getenv("RESEARCH_NO_CACHE") == "1" or not os.path.exists(CACHE_PATH):
        return None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            store = json.load(fh)
    except Exception:
        return None
    entry = store.get(_cache_key(company_name, country))
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > CACHE_TTL_DAYS * 86400:
        return None
    return entry.get("data")


def cache_save(company_name, country, data):
    if os.getenv("RESEARCH_NO_CACHE") == "1":
        return
    store = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                store = json.load(fh)
        except Exception:
            store = {}
    store[_cache_key(company_name, country)] = {"ts": time.time(), "data": data}
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(store, fh, ensure_ascii=False)
    except Exception:
        pass


# ==========================================
# CHINESE -> ENGLISH ADDRESS TRANSLATION
# ==========================================

CN_PROVINCE = {
    "北京": "Beijing", "天津": "Tianjin", "上海": "Shanghai", "重庆": "Chongqing",
    "河北": "Hebei", "山西": "Shanxi", "辽宁": "Liaoning", "吉林": "Jilin",
    "黑龙江": "Heilongjiang", "江苏": "Jiangsu", "浙江": "Zhejiang", "安徽": "Anhui",
    "福建": "Fujian", "江西": "Jiangxi", "山东": "Shandong", "河南": "Henan",
    "湖北": "Hubei", "湖南": "Hunan", "广东": "Guangdong", "海南": "Hainan",
    "四川": "Sichuan", "贵州": "Guizhou", "云南": "Yunnan", "陕西": "Shaanxi",
    "甘肃": "Gansu", "青海": "Qinghai", "台湾": "Taiwan", "内蒙古": "Inner Mongolia",
    "广西": "Guangxi", "西藏": "Tibet", "宁夏": "Ningxia", "新疆": "Xinjiang",
    "香港": "Hong Kong", "澳门": "Macau",
}

CN_CITY = {
    "北京": "Beijing", "上海": "Shanghai", "天津": "Tianjin", "重庆": "Chongqing",
    "广州": "Guangzhou", "深圳": "Shenzhen", "东莞": "Dongguan", "佛山": "Foshan",
    "珠海": "Zhuhai", "汕头": "Shantou", "中山": "Zhongshan", "惠州": "Huizhou",
    "杭州": "Hangzhou", "宁波": "Ningbo", "温州": "Wenzhou", "绍兴": "Shaoxing",
    "嘉兴": "Jiaxing", "台州": "Taizhou", "金华": "Jinhua", "湖州": "Huzhou",
    "苏州": "Suzhou", "无锡": "Wuxi", "常州": "Changzhou", "南京": "Nanjing",
    "南通": "Nantong", "扬州": "Yangzhou", "镇江": "Zhenjiang", "徐州": "Xuzhou",
    "连云港": "Lianyungang", "泰州": "Taizhou", "盐城": "Yancheng",
    "青岛": "Qingdao", "济南": "Jinan", "淄博": "Zibo", "潍坊": "Weifang",
    "烟台": "Yantai", "威海": "Weihai", "东营": "Dongying", "临沂": "Linyi",
    "济宁": "Jining", "枣庄": "Zaozhuang", "菏泽": "Heze", "德州": "Dezhou",
    "郑州": "Zhengzhou", "洛阳": "Luoyang", "武汉": "Wuhan", "宜昌": "Yichang",
    "长沙": "Changsha", "岳阳": "Yueyang", "南昌": "Nanchang", "九江": "Jiujiang",
    "合肥": "Hefei", "芜湖": "Wuhu", "安庆": "Anqing", "铜陵": "Tongling",
    "福州": "Fuzhou", "厦门": "Xiamen", "泉州": "Quanzhou", "漳州": "Zhangzhou",
    "石家庄": "Shijiazhuang", "邯郸": "Handan", "沧州": "Cangzhou", "唐山": "Tangshan",
    "保定": "Baoding", "太原": "Taiyuan", "西安": "Xi'an", "兰州": "Lanzhou",
    "成都": "Chengdu", "昆明": "Kunming", "贵阳": "Guiyang", "南宁": "Nanning",
    "沈阳": "Shenyang", "大连": "Dalian", "鞍山": "Anshan", "锦州": "Jinzhou",
    "长春": "Changchun", "吉林": "Jilin", "哈尔滨": "Harbin", "大庆": "Daqing",
    "呼和浩特": "Hohhot", "乌鲁木齐": "Urumqi", "海口": "Haikou",
    "银川": "Yinchuan", "西宁": "Xining", "拉萨": "Lhasa", "潮州": "Chaozhou",
}

# Ordered longest-first so "经济技术开发区" wins over "开发区".
CN_TERMS = [
    ("经济技术开发区", " Economic & Technological Development Zone"),
    ("高新技术产业开发区", " Hi-Tech Industrial Development Zone"),
    ("高新技术开发区", " Hi-Tech Development Zone"),
    ("工业园区", " Industrial Park"),
    ("化工园区", " Chemical Industrial Park"),
    ("保税区", " Free Trade Zone"),
    ("开发区", " Development Zone"),
    ("高新区", " Hi-Tech Zone"),
    ("工业园", " Industrial Park"),
    ("科技园", " Science Park"),
    ("产业园", " Industrial Park"),
    ("自治区", " Autonomous Region"),
    ("大厦", " Building"),
    ("大道", " Avenue"),
    ("广场", " Plaza"),
    ("中心", " Center"),
    ("小区", " Residential Area"),
    ("新区", " New District"),
    ("园区", " Park"),
    ("省", " Province"),
    ("市", " City"),
    ("区", " District"),
    ("县", " County"),
    ("镇", " Town"),
    ("乡", " Township"),
    ("村", " Village"),
    ("街道", " Subdistrict"),
    ("路", " Road"),
    ("街", " Street"),
    ("巷", " Lane"),
    ("弄", " Alley"),
    ("号楼", " Building No."),
    ("号", " No."),
    ("栋", " Block"),
    ("座", " Block"),
    ("层", "F"),
    ("楼", "F"),
    ("室", " Room"),
    ("单元", " Unit"),
    ("邮编", " Postcode "),
    ("中国", " China"),
]


CN_TITLES = {
    "先生": "Mr.", "女士": "Ms.", "小姐": "Ms.",
    "经理": "Manager", "总经理": "General Manager", "副总经理": "Deputy General Manager",
    "销售经理": "Sales Manager", "外贸经理": "Export Manager", "业务经理": "Business Manager",
    "总监": "Director", "董事长": "Chairman", "总裁": "President",
    "法定代表人": "Legal Representative", "负责人": "Person in Charge", "总": "Director",
}

# Address segment suffixes, longest first so 工业园区 beats 园区 beats 区.
CN_SEG_SUFFIX = {
    "经济技术开发区": "Economic & Technological Development Zone",
    "高新技术产业开发区": "Hi-Tech Industrial Development Zone",
    "高新技术开发区": "Hi-Tech Development Zone",
    "工业园区": "Industrial Park", "化工园区": "Chemical Industrial Park",
    "保税区": "Free Trade Zone", "开发区": "Development Zone", "高新区": "Hi-Tech Zone",
    "高科技园区": "Hi-Tech Park", "科技园区": "Science & Technology Park",
    "工业园": "Industrial Park", "科技园": "Science Park", "产业园": "Industrial Park",
    "园区": "Park", "新区": "New District", "街道": "Subdistrict", "小区": "Residential Area",
    "大厦": "Building", "广场": "Plaza", "中心": "Center", "大道": "Avenue",
    "区": "District", "县": "County", "镇": "Town", "乡": "Township", "村": "Village",
    "路": "Road", "街": "Street", "巷": "Lane", "弄": "Alley",
}

# Suffixes that take a leading number in English: 399号 -> "No. 399".
CN_SEG_NUMERIC = {
    "号楼": "Building {}", "号": "No. {}", "室": "Room {}", "单元": "Unit {}",
    "栋": "Block {}", "座": "Block {}", "层": "{}F", "楼": "{}F",
}

_ALL_SEG = sorted(list(CN_SEG_SUFFIX) + list(CN_SEG_NUMERIC), key=len, reverse=True)
SEG_RE = re.compile(r"([一-鿿A-Za-z0-9]+?)(" + "|".join(map(re.escape, _ALL_SEG)) + ")")


def _translate_online(text):
    if not GoogleTranslator:
        return None
    try:
        out = GoogleTranslator(source="zh-CN", target="en").translate(text)
        return out.strip() if out else None
    except Exception:
        return None


# Generic components of Chinese place names that have real English equivalents.
CN_GENERIC_WORDS = [
    ("经济技术", "Economic & Technological"), ("高新技术", "Hi-Tech"),
    ("新材料", "New Materials"), ("生物医药", "Biopharmaceutical"),
    ("化工", "Chemical"), ("工业", "Industrial"), ("科技", "Technology"),
    ("高新", "Hi-Tech"), ("生物", "Bio"), ("医药", "Pharmaceutical"),
    ("汽车", "Auto"), ("电子", "Electronics"), ("物流", "Logistics"),
    ("国际", "International"), ("中央", "Central"),
]


def romanize(text):
    """Chinese -> latin: known generic words translated, the rest via pypinyin."""
    if not text or not has_cjk(text):
        return text

    parts, buf = [], text
    for zh, en in CN_GENERIC_WORDS:
        buf = buf.replace(zh, f"\x00{en}\x00")

    for chunk in buf.split("\x00"):
        if not chunk:
            continue
        if has_cjk(chunk) and lazy_pinyin:
            parts.append(" ".join(p.capitalize() for p in lazy_pinyin(chunk)))
        else:
            parts.append(chunk)
    return " ".join(parts).strip()


def romanize_person(name):
    """Chinese personal name -> 'Zhang Wei' style. Never address-translated."""
    if not name or not has_cjk(name):
        return name
    if lazy_pinyin:
        parts = lazy_pinyin(name)
        if len(parts) >= 2:
            return parts[0].capitalize() + " " + "".join(parts[1:]).capitalize()
    return name


def translate_cn_title(title):
    if not title:
        return None
    return CN_TITLES.get(title.strip(), romanize(title.strip()))


def translate_cn_address(text):
    """Chinese address -> English, reordered small->large (English convention).

    Uses deep-translator when installed; otherwise an offline gazetteer plus a
    segment parser, with pypinyin romanising the remaining proper nouns.
    """
    if not text or not has_cjk(text):
        return text

    online = _translate_online(text)
    if online and not has_cjk(online):
        return online

    body = text.strip()

    province = None
    for zh, en in sorted(CN_PROVINCE.items(), key=lambda kv: -len(kv[0])):
        for form in (zh + "省", zh + "自治区", zh + "市", zh):
            if form in body:
                province, body = en, body.replace(form, "", 1)
                break
        if province:
            break

    city = None
    for zh, en in sorted(CN_CITY.items(), key=lambda kv: -len(kv[0])):
        for form in (zh + "市", zh):
            if form in body:
                city, body = en, body.replace(form, "", 1)
                break
        if city:
            break

    if city and province == city:
        province = None  # municipalities: Shanghai, Beijing, Tianjin, Chongqing

    body = body.replace("中国", "").strip(" ,，、。")

    segments, cursor = [], 0
    for match in SEG_RE.finditer(body):
        if match.start() > cursor:
            leftover = body[cursor:match.start()].strip(" ,，、")
            if leftover in {"区", "市", "省", "县", "号"}:
                leftover = ""
            if leftover:
                segments.append(romanize(leftover))
        name, suffix = match.group(1), match.group(2)
        if suffix in CN_SEG_NUMERIC:
            segments.append(CN_SEG_NUMERIC[suffix].format(romanize(name)))
        else:
            segments.append(f"{romanize(name)} {CN_SEG_SUFFIX[suffix]}".strip())
        cursor = match.end()

    tail = body[cursor:].strip(" ,，、。")
    if tail:
        segments.append(romanize(tail))

    segments.reverse()  # Chinese runs big -> small; English runs small -> big
    parts = [s for s in segments if s] + [p for p in (city, province, "China") if p]
    return re.sub(r"\s+", " ", ", ".join(parts)).strip(", ")


def translate_cn_snippet(text, limit=300):
    """Best-effort translation of a short Chinese phrase."""
    if not text or not has_cjk(text):
        return text
    online = _translate_online(text[:limit])
    return online if online else romanize(text[:limit])


# ==========================================
# COUNTRY-AWARE PHONE HANDLING
# ==========================================

def normalize_phone(raw, profile):
    """Return E.164 for the selected country, accepting both local and +country-code forms."""
    if not raw:
        return None
    cc = profile["dial_code"]
    original = re.sub(r"\D", "", str(raw))
    if not original:
        return None

    # Try the number exactly as supplied, then as an international number with
    # the country code removed. This fixes forms such as 86-10-59960028.
    candidates = [original]
    if original.startswith("00" + cc):
        candidates.insert(0, original[2 + len(cc):])
    elif original.startswith(cc):
        candidates.insert(0, original[len(cc):])

    lo, hi = profile["nsn_len"]
    for digits in candidates:
        local = digits.lstrip("0")
        if not (lo <= len(local) <= hi):
            continue
        for pattern in profile["phone_patterns"]:
            if re.fullmatch(pattern, local):
                return "+" + cc + local
    return None


def extract_phone(text, profile):
    """Extract a validated phone number, prioritising labelled Chinese numbers."""
    if not text:
        return None
    for value in re.findall(r"PHONE:\s*([^\n]+)", text, re.IGNORECASE):
        phone = normalize_phone(value, profile)
        if phone:
            return phone
    if profile.get("query_lang") == "zh":
        labelled = re.findall(r"(?:联系地址|联系电话|公司电话|电话|手机|手机号|热线|客户服务热线)\s*[:：]?\s*([+]?\d[\d\s\-()（）]{5,22})", text, re.IGNORECASE)
        for value in labelled:
            phone = normalize_phone(value, profile)
            if phone:
                return phone
    candidates = re.findall(r"(?:\+?\d[\d\s\-\(\)（）]{7,22}\d)", text.replace("‐", "-").replace("–", "-").replace("—", "-"))
    for value in candidates:
        phone = normalize_phone(value, profile)
        if phone:
            return phone
    return None


def extract_whatsapp(text, profile):
    if not text:
        return None

    patterns = [
        r"wa\.me/(\d{8,15})",
        r"whatsapp\.com/send\?phone=(\d{8,15})",
        r"WHATSAPP:\s*([^\n]+)",
        r"WhatsApp[\s:：,\-]*(\+?\d[\d\s\-]{7,18}\d)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            phone = normalize_phone(match.group(1), profile)
            if phone:
                return phone
    return None


WECHAT_ID_RE = r"([A-Za-z][A-Za-z0-9_\-]{5,19})"


def extract_wechat(text, profile):
    """WeChat ID or the mobile number used as the WeChat account."""
    if not text:
        return None

    id_patterns = [
        r"(?:微信号|微信|weixin|wechat)\s*(?:ID|id)?\s*[:：]\s*" + WECHAT_ID_RE,
        r"(?:WeChat|Wechat|WECHAT)\s*[:：]?\s*" + WECHAT_ID_RE,
    ]
    for pattern in id_patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1)
            if candidate.lower() not in {"account", "official", "contact", "scanqr"}:
                return candidate

    num_patterns = [
        r"(?:微信号|微信|weixin|wechat|WeChat)\s*(?:ID|id)?\s*[:：]?\s*(\+?\d[\d\s\-]{8,18}\d)",
        r"(\+?\d[\d\s\-]{8,18}\d)\s*(?:同微信|即微信|微信同号)",
    ]
    for pattern in num_patterns:
        match = re.search(pattern, text)
        if match:
            phone = normalize_phone(match.group(1), profile)
            if phone:
                return phone
    return None


# ==========================================
# EMAIL
# ==========================================

BAD_EMAIL_MARKERS = [
    "example.com", "test.com", "domain.com", "noreply", "no-reply",
    "sentry.io", "indiamart.com", "justdial.com", "made-in-china.com",
    "alibaba.com", "wixpress.com", "godaddy.com", "u.email",
]


def extract_official_email(text, official_website, company_name, country):
    if not text:
        return None

    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if not emails:
        return None

    official_domain = source_domain(official_website)
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(company_name)]

    candidates = []
    for email in emails:
        email = email.strip(".,;:()[]<>")
        lower = email.lower()
        if any(bad in lower for bad in BAD_EMAIL_MARKERS):
            continue

        email_domain = lower.split("@", 1)[-1]
        score = 0

        if official_domain:
            if email_domain == official_domain:
                score += 100
            elif email_domain.endswith("." + official_domain):
                score += 90

        if tokens and any(t in re.sub(r"[^a-z0-9]", "", email_domain) for t in tokens):
            score += 50

        # In China a 163/qq/126 mailbox is a normal business address.
        if country == "CN" and email_domain in CN_FREEMAIL:
            score += 35

        if any(lower.startswith(p) for p in (
            "sales@", "info@", "contact@", "marketing@", "enquiry@",
            "enquiries@", "business@", "export@", "trade@", "admin@",
        )):
            score += 10

        if score > 0 or not official_domain:
            candidates.append((score, email))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    return candidates[0][1]


# ==========================================
# CONTACT PERSON
# ==========================================

def valid_contact_person(name):
    if not name:
        return None

    cleaned = re.sub(r"\s+", " ", name.replace("\\n", " ")).strip()
    words = re.findall(r"[A-Za-z]+", cleaned)
    if not 2 <= len(words) <= 3:
        return None

    for w in words:
        wl = w.lower()
        if wl in STOP_WORDS or wl in GENERIC_NAMES or wl in MARKETING_WORDS:
            return None
        if wl.endswith(("ed", "ing", "tion", "sion", "ment", "ance")):
            return None

    return " ".join(w.capitalize() for w in words)


CN_SURNAMES = (
    "王李张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
    "肖田董潘袁蔡蒋余于杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
)


def valid_cn_contact_person(name):
    """Chinese personal names: 2-4 characters, first char a plausible surname."""
    if not name:
        return None
    name = name.strip()
    if not (2 <= len(name) <= 4) or not all(CJK_RE.match(c) for c in name):
        return None
    if name[0] not in CN_SURNAMES:
        return None
    return name


def extract_verified_contact_person(blocks, country):
    if not blocks:
        return None, None

    if country == "CN":
        cn_patterns = [
            (r"(?:联系人|联 系 人|负责人)\s*[:：]\s*([一-鿿]{2,4})\s*(先生|女士|经理|总经理|总监|董事长|总)?", None),
            (r"([一-鿿]{2,4})\s*(先生|女士|经理|总经理|总监|董事长|法定代表人)", None),
            (r"(?:法定代表人|董事长|总经理)\s*[:：]\s*([一-鿿]{2,4})", None),
        ]
        for block in blocks:
            for pattern, _ in cn_patterns:
                match = re.search(pattern, block)
                if match:
                    person = valid_cn_contact_person(match.group(1))
                    if person:
                        title = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                        english = romanize_person(person)
                        label = f"{person} ({english})" if english != person else person
                        return label, translate_cn_title(title)
        # fall through to latin patterns for bilingual sites

    patterns = [
        r"(?:Director|Managing Director|MD|CEO|Founder|Proprietor|General Manager|Key Person)\s*[:\-]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:Contact Person|Contact Name)\s*[:\-]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
        r"\b(?:Mr\.?|Ms\.?|Mrs\.?)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\b",
    ]
    for block in blocks:
        for pattern in patterns:
            match = re.search(pattern, block)
            if match:
                person = valid_contact_person(match.group(1))
                if person:
                    return person, None
    return None, None


# ==========================================
# LOCATION / ADDRESS
# ==========================================

ADDRESS_CONTEXT_EN = (
    r"\b(?:registered office|corporate office|head office|headquarters|address|"
    r"location|ROC|factory|plant|based in)\b[^\n]{0,220}"
)
ADDRESS_CONTEXT_ZH = r"(?:联系地址|公司地址|注册地址|办公地址|办公地点|总部地址|总部|厂址|地址|地 址)\s*[:：]?[^\n]{0,180}"


ADDRESS_HINT_WORDS_EN = (
    "street", "road", "avenue", "district", "building", "floor", "suite",
    "block", "industrial", "province", "highway", "lane", "drive",
    "boulevard", "p.o. box", "postal code", "zip code", "county",
)


def looks_like_address(text, profile=None):
    """Reject scraped noise that happened to sit near an address keyword.

    The keyword-context regex fires on any occurrence of "address",
    "location", "plant", etc. - including inside spec-sheet labels ("Plant
    Size:"), product codes, and prose that merely contains that substring
    ("power[plant]"). Two layers of defense:

    1. Structural: real addresses (in any language) are several whitespace-
       separated words, not one short word or one long unbroken run of
       characters (an obfuscated JS blob/token still uses "/", "+", "-" as
       filler, so splitting on punctuation instead of whitespace would miss
       it).
    2. Content: require some positive evidence it's actually a location -
       a street/building keyword, a known city for this country, or the
       digit+comma shape of "<number> ... Street, City, Country".
    """
    if not text:
        return False
    if len(text) < 8:
        return False
    if len(text) > 15 and len(text.split()) < 2:
        return False
    if re.search(r"\S{30,}", text):
        return False

    lower = text.lower()
    has_keyword = any(k in lower for k in ADDRESS_HINT_WORDS_EN)
    has_city = bool(profile) and any(c.lower() in lower for c in profile.get("cities", []))
    has_digit_and_comma = bool(re.search(r"\d", text)) and "," in text
    return has_keyword or has_city or has_digit_and_comma


def extract_location(text, profile, country):
    """Return (english_city, english_address, original_address)."""
    if not text:
        return None, None, None

    city = None
    address_raw = None

    if country == "CN":
        zh_hits = re.findall(ADDRESS_CONTEXT_ZH, text)
        if zh_hits:
            candidates = []
            for hit in zh_hits:
                cleaned = re.sub(r"^(联系地址|公司地址|注册地址|办公地址|办公地点|总部地址|总部|厂址|地址|地\s*址)\s*[:：]?\s*", "", hit).strip(" \t,，。;；")
                # Profile pages run the address straight into the next section
                # ("...22号查看地图 经营范围：..."); keep only the address part.
                cleaned = china_sources.trim_cn_address(cleaned)
                if cleaned and has_cjk(cleaned) and len(cleaned) >= 6:
                    score = (30 if any(k in hit for k in ("联系地址","公司地址","注册地址","办公地址","总部地址")) else 0)
                    score += (20 if any(k in cleaned for k in ("省","市","区","路","街","号","大厦","园区")) else 0)
                    candidates.append((score, cleaned))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], len(x[1])))
                address_raw = candidates[0][1]
        for zh, en in sorted(CN_CITY.items(), key=lambda kv: -len(kv[0])):
            if zh in text:
                city = en
                break

    contexts = re.findall(ADDRESS_CONTEXT_EN, text, re.IGNORECASE)
    if not address_raw and contexts:
        for ctx in contexts:
            candidate = re.sub(
                r"^(registered office|corporate office|head office|headquarters|address|location|factory|plant)\s*[:\-]?\s*",
                "", ctx, flags=re.IGNORECASE,
            ).strip()
            if looks_like_address(candidate, profile):
                address_raw = candidate
                break

    if not city:
        haystack = " ".join(contexts) if contexts else text
        for candidate in profile["cities"]:
            if re.search(rf"\b{re.escape(candidate)}\b", haystack, re.IGNORECASE):
                city = candidate
                break

    address_en = None
    if address_raw:
        address_en = translate_cn_address(address_raw) if has_cjk(address_raw) else address_raw
        address_en = re.sub(r"\s+", " ", address_en).strip()

    return city, address_en, (address_raw if address_raw and has_cjk(address_raw) else None)


# ==========================================
# INDUSTRY / PRODUCTS
# ==========================================

INDUSTRY_RULES = [
    ("Chemical Distribution & Trading", [
        r"\bchemical distribution\b", r"\bchemical distributor\b",
        r"\bdistributor of chemicals\b", r"\bchemical indenting\b",
        r"\bchemical trading\b", r"\bspecialty chemicals distribution\b",
        r"化工贸易", r"化学品分销", r"化工经销",
    ]),
    ("Chemical Manufacturing & Specialty Chemicals", [
        r"\bchemical manufactur\w*\b", r"\bspecialty chemicals\b",
        r"\bperformance chemicals\b", r"\bindustrial chemicals\b",
        r"\bfine chemicals\b", r"精细化工", r"化工有限公司", r"化学有限公司",
    ]),
    ("Active Pharmaceutical Ingredients (API)", [
        r"\bapi manufactur\w*\b", r"\bactive pharmaceutical ingredient\b",
        r"\bbulk drug\b", r"原料药",
    ]),
    ("Pharmaceuticals", [
        r"\bpharmaceutical formulation\b", r"\bpharma company\b",
        r"\bfinished dosage\b", r"\bpharmaceutical manufactur\w*\b", r"制药",
    ]),
    ("Polymers & Plastic Raw Materials", [
        r"\bpolymer distribution\b", r"\bpolymer manufactur\w*\b",
        r"\bplastic raw material\b", r"\bmasterbatch\w*\b", r"\bresin\b",
        r"塑料原料", r"高分子材料", r"色母粒",
    ]),
    ("Pipes & Fittings Manufacturing", [
        r"\bpvc pipes?\b", r"\bcpvc pipes?\b", r"\bhdpe pipes?\b",
        r"\bpipe manufactur\w*\b", r"管材",
    ]),
    ("Packaging Materials", [
        r"\bpackaging solutions\b", r"\bpet preforms?\b", r"\bbopp\b",
        r"\bflexible packaging\b", r"包装材料",
    ]),
]


def extract_industry(text):
    if not text:
        return None
    for industry_name, patterns in INDUSTRY_RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return industry_name
    return None


PRODUCT_KEYWORDS = [
    "API", "Active Pharmaceutical Ingredients", "Intermediates", "Formulations",
    "Bulk Drugs", "Pellets", "PVC pipes", "PVC fittings", "CPVC pipes",
    "HDPE pipes", "PP woven bags", "PET bottles", "PET preforms",
    "Plastic packaging", "Packaging Films", "Specialty Chemicals",
    "Industrial Valves", "Masterbatch", "Titanium Dioxide", "Caustic Soda",
    "Soda Ash", "Solvents", "Surfactants", "Pigments", "Additives", "Resins",
]

PRODUCT_KEYWORDS_ZH = {
    "原料药": "API", "中间体": "Intermediates", "钛白粉": "Titanium Dioxide",
    "烧碱": "Caustic Soda", "纯碱": "Soda Ash", "溶剂": "Solvents",
    "表面活性剂": "Surfactants", "颜料": "Pigments", "助剂": "Additives",
    "树脂": "Resins", "色母粒": "Masterbatch", "管材": "Pipes",
}


def extract_products(text):
    if not text:
        return []
    found = []
    for p in PRODUCT_KEYWORDS:
        if re.search(rf"\b{re.escape(p)}\b", text, re.IGNORECASE):
            found.append(p)
    for zh, en in PRODUCT_KEYWORDS_ZH.items():
        if zh in text:
            found.append(en)
    return list(dict.fromkeys(found))[:10]


# ==========================================
# FETCH & PARSE
# ==========================================

HEADERS_BY_LANG = {
    "en": "en-US,en;q=0.9",
    "zh": "zh-CN,zh;q=0.9,en;q=0.6",
    "de": "de-DE,de;q=0.9,en;q=0.6",
    "vi": "vi-VN,vi;q=0.9,en;q=0.6",
    "ko": "ko-KR,ko;q=0.9,en;q=0.6",
    "ja": "ja-JP,ja;q=0.9,en;q=0.6",
}

BLOCK_TAGS = ["p", "li", "span", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "a"]


def build_headers(profile):
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": HEADERS_BY_LANG.get(profile.get("hl", "en"), "en-US,en;q=0.9"),
    }


def extract_text_blocks(soup):
    blocks = []
    for tag in soup.find_all(BLOCK_TAGS):
        if tag.find(BLOCK_TAGS):
            continue
        text = tag.get_text(" ", strip=True)
        if text:
            blocks.append(text)
    return blocks


def parse_page_content(html, url):
    collected_text, collected_blocks = [], []
    soup = BeautifulSoup(html, "html.parser")

    for cf in soup.select("[data-cfemail]"):
        decoded = decode_cf_email(cf.get("data-cfemail", ""))
        if decoded:
            collected_text.append(f"EMAIL: {decoded}")

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        low = href.lower()
        if low.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if email:
                collected_text.append(f"EMAIL: {email}")
        elif low.startswith("tel:"):
            phone = href[4:].strip()
            if phone:
                collected_text.append(f"PHONE: {phone}")
        elif "wa.me/" in low or "whatsapp.com" in low:
            collected_text.append(f"WHATSAPP: {href}")
        elif "weixin.qq.com" in low or "wechat" in low:
            collected_text.append(f"WeChat: {href}")

    collected_blocks.extend(extract_text_blocks(soup))

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    if text:
        collected_text.append(f"\nSOURCE: {url}\n{text}")

    return "\n".join(collected_text), collected_blocks


def fetch_url_data(url, profile, timeout=8, return_html=False):
    """Fetch one page, or give up fast.

    Every page fetch in the agent funnels through here, so this is where a
    geo/access wall is detected once and the host is then skipped for the rest
    of the run - Tianyancha in particular must never be retried, and its block
    page must never reach the extractors as if it were company data.

    return_html additionally hands back the raw markup so callers that need to
    walk links do not have to fetch the same page a second time.
    """
    empty = ("", [], "") if return_html else ("", [])

    if china_sources.is_blocked(url):
        return empty

    # This host already proved it drops :443 - do not pay the TLS timeout again.
    if url.lower().startswith("https://") and china_sources.prefers_http(url):
        url = "http://" + url[len("https://"):]

    try:
        # (connect, read) - a hung read must not stall the whole research run.
        response = requests.get(url, headers=build_headers(profile),
                                timeout=(5, timeout))
        if response.status_code != 200:
            # 404/410 means THIS path is missing, not that the host is closed
            # to us - the contact-page crawler guesses paths like /contact and
            # must not blocklist the company's own domain when one 404s.
            # Anything else (403, 419 anti-bot, 429, 5xx...) means retrying
            # this host during this run is wasted time.
            if response.status_code not in (404, 410):
                china_sources.mark_blocked(url, f"http_{response.status_code}")
            return empty

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding

        html = response.text
        text, blocks = parse_page_content(html, url)

        if china_sources.detect_geo_block(text, url) or china_sources.detect_geo_block(html, url):
            china_sources.mark_blocked(url, "geo_blocked")
            print(f"   ⛔ {china_sources.host_of(url)} served an access wall - skipping this host")
            return empty

        return (text, blocks, html) if return_html else (text, blocks)
    except requests.RequestException:
        # Some mainland-hosted sites accept :80 but drop :443 from outside
        # China (sinopec.com does exactly this), so an HTTPS connection
        # failure is not proof the site is unreachable. Retry once over
        # plain HTTP before writing the host off - this recovers the
        # company's OWN site, which is the most trustworthy source there is.
        if url.lower().startswith("https://"):
            downgraded = "http://" + url[len("https://"):]
            try:
                response = requests.get(downgraded, headers=build_headers(profile),
                                        timeout=(8, max(timeout, 15)))
                if response.status_code == 200:
                    if not response.encoding or response.encoding.lower() == "iso-8859-1":
                        response.encoding = response.apparent_encoding
                    html = response.text
                    text, blocks = parse_page_content(html, url)
                    if not china_sources.detect_geo_block(text, url):
                        china_sources.mark_http_only(url)
                        print(f"   ↩ {china_sources.host_of(url)} reachable over http (https blocked)")
                        return (text, blocks, html) if return_html else (text, blocks)
            except requests.RequestException:
                pass
        # Only after repeated failures - a single transient error on one page
        # must not disqualify the company's own website.
        china_sources.note_failure(url, "unreachable")
    return empty


# ==========================================
# WEBSITE IDENTIFICATION (country-aware)
# ==========================================

def company_search_names(company_name, country):
    names = [company_name.strip()]
    if country == "CN":
        key = normalize_name(company_name)
        for alias in CN_COMPANY_ALIASES.get(key, []):
            if alias not in names:
                names.append(alias)
    return names


def result_mentions_company(company_name, url, title, snippet, country, industry_hint=None):
    """Loose relevance gate for a raw search/portal result.

    A quoted-phrase Google query still returns near-matches and same-prefix
    homonyms (a different "Xinfa ..." company, a different firm's registry
    page) - especially for short, common transliterated name fragments. Only
    let a result feed into extracted fields or show up as a "source" once
    the company's own name tokens actually appear in its domain or its
    title/snippet text, instead of trusting every raw hit unconditionally.

    A single generic 4-5 letter token shared by many unrelated companies
    (e.g. many Chinese firms romanize to "Xinfa ...") can't be disambiguated
    by name alone. When the caller supplied an industry hint, require it to
    also show up in the result - a homonym in an unrelated line of business
    won't mention it, which is exactly the signal that filters it out.
    """
    domain = source_domain(url)
    flat_domain = re.sub(r"[^a-z0-9]", "", domain)
    blob = f"{title or ''} {snippet or ''}"
    flat_blob = re.sub(r"[^a-z0-9]", "", blob.lower())

    name_matched = False
    for name in company_search_names(company_name, country):
        tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(name)]
        if tokens and all(t in flat_domain or t in flat_blob for t in tokens):
            name_matched = True
            break
        if country == "CN" and has_cjk(name):
            core = re.sub(r"(有限公司|股份有限公司|集团|公司)$", "", name.strip())
            if core and (core in (title or "") or core in (snippet or "")):
                name_matched = True
                break
            if lazy_pinyin:
                py = "".join(lazy_pinyin(core))
                if len(py) >= 5 and (py in flat_domain or py in flat_blob):
                    name_matched = True
                    break
    if not name_matched:
        return False

    # Reuses only the tokenizer's length filter, not name_tokens()'s
    # LEGAL_SUFFIXES list - words like "chemicals" or "technology" are
    # exactly what an industry hint looks like, not noise to strip.
    hint_tokens = [w for w in normalize_name(industry_hint or "").split() if len(w) >= 4]
    if hint_tokens and not (has_cjk(industry_hint) and industry_hint.strip() in blob):
        if not any(t in flat_blob for t in hint_tokens):
            return False
    return True


def expected_official_domains(company_name, country):
    """Return verified/known official domains for high-confidence companies."""
    if country != "CN":
        return []
    key = normalize_name(company_name)
    domains = list(CN_OFFICIAL_DOMAIN_HINTS.get(key, []))
    # Also check the literal Chinese name when normalize_name() removes CJK.
    for name in company_search_names(company_name, country):
        domains.extend(CN_OFFICIAL_DOMAIN_HINTS.get(name, []))
    return list(dict.fromkeys(d.lower() for d in domains))


def domain_is_expected_official(url, company_name, country):
    domain = source_domain(url)
    return any(domain_matches(domain, expected) for expected in expected_official_domains(company_name, country))


def is_likely_news_or_article(url, title="", snippet=""):
    path = (url or "").lower()
    blob = f"{title} {snippet}".lower()
    # A company news/article page is still a company page, but it is NOT the
    # right page to use as the company's official contact source.
    if any(x in path for x in ("/news/", "/article/", "/articles/", "/press/", "/media/", "/story/", "/search/")):
        return True
    domain = source_domain(url)
    if domain in {"news.sina.com.cn", "news.qq.com", "sinopecnews.com.cn"}:
        return True
    if re.search(r"(?:^|[.-])(news|media|press|portal)(?:[.-]|$)", domain):
        return True
    if any(x in blob for x in CN_NEWS_WORDS) and not any(x in blob for x in CN_OFFICIAL_SIGNAL_WORDS):
        return True
    return False


def normalize_root_url(url):
    m = re.search(r"https?://(?:www\.)?[^/]+", url or "", re.IGNORECASE)
    return m.group(0).rstrip("/") if m else None


def score_website_candidate(company_name, url, title, snippet, country):
    domain = source_domain(url)
    if not domain or is_blocked_domain(url):
        return -100

    # Known official domains get a very large bonus.  This prevents a domain
    # such as sinopecnews.com.cn from beating the real sinopec.com domain just
    # because its title contains the company name.
    expected = domain_is_expected_official(url, company_name, country)
    if expected:
        return 1000

    if is_likely_news_or_article(url, title, snippet):
        return -100

    profile = COUNTRY_PROFILES[country]; flat_domain = re.sub(r"[^a-z0-9]", "", domain)
    name_match_score = 0
    for name in company_search_names(company_name, country):
        tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(name)]
        if tokens:
            hits = sum(1 for t in tokens if t in flat_domain)
            # A match on generic industry words alone means we found a
            # directory, not this company's site. Require the distinctive
            # part of the name to match too, when the name has one.
            distinctive = [t for t in tokens if t not in GENERIC_INDUSTRY_WORDS]
            distinctive_hits = sum(1 for t in distinctive if t in flat_domain)
            if hits and (distinctive_hits or not distinctive):
                name_match_score += 80 + 15 * (hits - 1)
        if country == "CN" and has_cjk(name):
            core = re.sub(r"(有限公司|股份有限公司|集团|公司)$", "", name.strip())
            if core and (core in (title or "") or core in (snippet or "")): name_match_score += 80
            if lazy_pinyin:
                py = "".join(lazy_pinyin(core))
                if len(py) >= 5 and py in flat_domain: name_match_score += 60

    # Generic "this looks like an official company page" signals (Chinese
    # contact boilerplate, CJK text, a local TLD) are only meaningful once the
    # domain has already shown *some* real evidence of being this company's
    # site. Without that, they let totally unrelated domains (any Chinese
    # site with a contact page and a .cn TLD) outscore the 40-point pick
    # threshold and get crowned "official" for the wrong company.
    if name_match_score == 0:
        return -50

    score = name_match_score
    blob = f"{title or ''} {snippet or ''}"
    if country == "CN":
        if any(x in blob for x in CN_OFFICIAL_SIGNAL_WORDS): score += 35
        if has_cjk(blob): score += 15
    if any(domain.endswith(t) for t in profile["tld_bonus"]): score += 25
    foreign_tlds = {".ca":"CA",".co.uk":"GB",".uk":"GB",".au":"AU",".ru":"RU",".br":"BR",".fr":"FR",".it":"IT",".es":"ES",".mx":"MX",".pl":"PL",".nl":"NL",".se":"SE",".ch":"CH",".at":"AT",".za":"ZA",".ng":"NG",".ke":"KE",".th":"TH",".my":"MY",".id":"ID",".ph":"PH",".pk":"PK",".bd":"BD",".lk":"LK",".ir":"IR",".sa":"SA",".eg":"EG",".tr":"TR",".il":"IL",".cn":"CN",".com.cn":"CN",".in":"IN",".co.in":"IN",".de":"DE",".ae":"AE",".vn":"VN",".com.vn":"VN",".kr":"KR",".co.kr":"KR",".jp":"JP",".co.jp":"JP"}
    for tld, owner in sorted(foreign_tlds.items(), key=lambda kv: -len(kv[0])):
        if domain.endswith(tld):
            if owner != country: score -= 100
            break
    if "/listco" in (url or "").lower(): score += 20
    return score - min(len(domain) // 12, 3)


def pick_official_website(company_name, results, country):
    # First pass: if Google returned the company's known official domain, use it
    # immediately.  Do not let a news mirror or similarly named domain win.
    expected_domains = expected_official_domains(company_name, country)
    canonical = CN_OFFICIAL_CANONICAL_URLS.get(normalize_name(company_name)) if country == "CN" else None
    for item in results:
        url = (item.get("link") or "").strip()
        if url and any(domain_matches(source_domain(url), d) for d in expected_domains):
            return canonical or normalize_root_url(url)

    # If the known official domain is not present in the first Google page,
    # still use the verified canonical URL for known companies. The later
    # contact-page crawl will validate whether the site is reachable.
    if canonical and expected_domains:
        return canonical

    best, best_score = None, 0
    for item in results:
        url = (item.get("link") or "").strip()
        if not url:
            continue
        score = score_website_candidate(
            company_name, url, item.get("title"), item.get("snippet"), country
        )
        if score > best_score:
            best, best_score = url, score
    if not best or best_score < 40:
        return None
    return normalize_root_url(best)


def build_web_query(company_name, country, industry_hint=None):
    profile = COUNTRY_PROFILES[country]; hint = f" {industry_hint}" if industry_hint else ""
    if profile["query_lang"] == "zh":
        return f'"{company_name}"{hint} 官网 官方网站 联系方式 联系电话 地址 公司'
    return f'"{company_name}"{hint} {profile["name"]} official website company contact email phone'


def search_web(company_name, country, industry_hint=None, num=8):
    profile = COUNTRY_PROFILES[country]
    names = company_search_names(company_name, country)
    results, seen = [], set()

    if country == "CN":
        # Search the known official domain directly first.  This is the key
        # change for companies such as Sinopec: Google must not be allowed to
        # decide that a similarly named news site is the company website.
        expected = expected_official_domains(company_name, country)
        for domain in expected:
            batch = serp_search(
                {
                    "engine": "google",
                    "q": f'site:{domain} "{company_name}" (官网 OR 官方网站 OR 联系我们 OR 联系方式 OR 地址 OR 电话)',
                    "num": num,
                    "gl": profile["gl"],
                    "hl": profile["hl"],
                    "google_domain": profile["google_domain"],
                },
                f"official domain search ({domain})",
            )
            for item in batch:
                link = item.get("link")
                if link and link not in seen:
                    seen.add(link); results.append(item)

        hint = f" {industry_hint}" if industry_hint else ""
        for name in names:
            batch = serp_search(
                {
                    "engine": "google",
                    "q": f'"{name}"{hint} 官网 官方网站 联系方式 联系电话 地址 公司',
                    "num": num,
                    "gl": profile["gl"],
                    "hl": profile["hl"],
                    "google_domain": profile["google_domain"],
                },
                f"web search ({profile['name']}) [{name}]",
            )
            for item in batch:
                link = item.get("link")
                if link and link not in seen:
                    seen.add(link); results.append(item)

        # Chinese exporters that market internationally are often only
        # findable under their romanized name on English-language B2B
        # directories - a purely Chinese-keyword query never surfaces those
        # pages at all. Widen the net with one English-oriented query
        # whenever the company name itself has no CJK to search natively.
        if not has_cjk(company_name):
            batch = serp_search(
                {
                    "engine": "google",
                    "q": f'"{company_name}"{hint} China official website company contact email phone',
                    "num": num,
                    "gl": profile["gl"],
                    "hl": "en",
                    "google_domain": profile["google_domain"],
                },
                f"web search ({profile['name']}) [en]",
            )
            for item in batch:
                link = item.get("link")
                if link and link not in seen:
                    seen.add(link); results.append(item)
        return results

    return serp_search(
        {
            "engine": "google",
            "q": build_web_query(company_name, country, industry_hint),
            "num": num,
            "gl": profile["gl"],
            "hl": profile["hl"],
            "google_domain": profile["google_domain"],
        },
        f"web search ({profile['name']})",
    )


LINK_HINTS = ("联系", "地址", "电话", "contact", "about", "公司简介", "联系方式", "lianxi", "lxwm")


def search_official_contact_pages(official_url, profile, country):
    """Crawl the company's own site for contact pages.

    Pages are fetched in small parallel batches: a mainland-hosted page can
    take ~10s to answer from outside China, and eight of those in sequence is
    over a minute of pure waiting. Concurrency is capped low and stays within
    one domain, so this is gentler than a burst of parallel requests across
    many hosts. Ordering of results is preserved to keep extraction stable.
    """
    data = {"text": "", "blocks": [], "sources": []}
    visited = set()

    # Probe the homepage on its own BEFORE fanning out. Firing the whole batch
    # at once would send every URL to :443 simultaneously, so a host that only
    # answers on :80 would rack up parallel timeouts and get blocklisted
    # before the first success could record the downgrade.
    root = official_url.rstrip("/")
    visited.add(root)
    root_text, root_blocks, root_html = fetch_url_data(root, profile, timeout=12, return_html=True)
    if root_text:
        data["text"] += "\n" + root_text
        data["blocks"].extend(root_blocks)
        data["sources"].append(root)

    frontier = []
    for path in (CONTACT_PATHS_ZH if country == "CN" else CONTACT_PATHS_EN):
        frontier.append(urljoin(official_url + "/", path))

    def eligible(candidate):
        candidate = (candidate or "").rstrip("/")
        return (candidate and candidate not in visited
                and source_domain(candidate) == source_domain(official_url)
                and not china_sources.is_blocked(candidate))

    # The homepage's own "contact us" link is usually the real contact page,
    # and beats the guessed paths.
    if root_html:
        try:
            for a in BeautifulSoup(root_html, "html.parser").find_all("a", href=True):
                href = urljoin(root, a.get("href", "").strip())
                low = (a.get_text(" ", strip=True) + " " + href).lower()
                if any(x in low for x in LINK_HINTS) and eligible(href):
                    frontier.insert(0, href)
        except Exception:
            pass

    # Two waves: the guessed contact paths, then anything they linked to.
    for _wave in range(2):
        batch, seen_in_batch = [], set()
        for candidate in frontier:
            candidate = (candidate or "").rstrip("/")
            if eligible(candidate) and candidate not in seen_in_batch:
                batch.append(candidate)
                seen_in_batch.add(candidate)
            if len(visited) + len(batch) >= 8:
                break
        if not batch:
            break
        visited.update(batch)

        # One request per page - this used to fetch each page a SECOND time
        # just to walk its links.
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(
                lambda t: (t,) + fetch_url_data(t, profile, timeout=12, return_html=True),
                batch,
            ))

        frontier = []
        for target, page_text, page_blocks, html in fetched:
            if not page_text:
                continue
            data["text"] += "\n" + page_text
            data["blocks"].extend(page_blocks)
            data["sources"].append(target)
            if not html:
                continue
            # Only follow links that look like they lead to contact details.
            try:
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                continue
            for a in soup.find_all("a", href=True):
                href = urljoin(target, a.get("href", "").strip())
                low = (a.get_text(" ", strip=True) + " " + href).lower()
                if any(x in low for x in LINK_HINTS) and eligible(href):
                    frontier.append(href)
    return data


PORTAL_BATCH_SIZE = 8


def search_country_portals(company_name, country, industry_hint=None):
    """Search that country's B2B portal set, in batches, cheapest-first."""
    profile = COUNTRY_PROFILES[country]
    portal_data = {"text": "", "blocks": [], "sources": []}

    if not profile["portals"]:
        return portal_data

    hint = f" {industry_hint}" if industry_hint else ""
    portals = profile["portals"]
    # Google degrades badly once too many site: operators are OR'd together,
    # so the portal set is searched in batches instead of one giant query.
    # Batches run in priority order and stop as soon as a batch yields usable
    # contact data, so the extra directories cost nothing on the common path.
    batches = [portals[i:i + PORTAL_BATCH_SIZE] for i in range(0, len(portals), PORTAL_BATCH_SIZE)]
    kept_total = 0

    for index, batch in enumerate(batches, start=1):
        results = serp_search(
            {
                "engine": "google",
                "q": f'"{company_name}"{hint} ({" OR ".join(batch)})',
                "num": 8,
                "gl": profile["gl"],
                "hl": profile["hl"],
                "google_domain": profile["google_domain"],
            },
            f"portal search ({profile['name']}) batch {index}/{len(batches)}",
        )

        for item in results:
            link = item.get("link", "")
            if not any(host in link for host in profile["portal_hosts"]):
                continue
            if china_sources.is_blocked(link):
                continue

            title = item.get("title", "")
            snippet = item.get("snippet", "")
            if not result_mentions_company(company_name, link, title, snippet, country, industry_hint):
                continue  # matched the portal query, but not evidently this company
            if link in portal_data["sources"]:
                continue

            portal_data["sources"].append(link)
            # Emit the same "SOURCE: <url>" marker parse_page_content() uses,
            # so per-field attribution can credit portal-derived values
            # instead of reporting source: null for them.
            portal_data["text"] += f"\nSOURCE: {link}\nPORTAL_DATA:\n{title}\n{snippet}\n"
            portal_data["blocks"].extend([title, snippet])
            kept_total += 1

            page_text, page_blocks = fetch_url_data(link, profile, timeout=8)
            if page_text:
                portal_data["text"] += f"\n{page_text}\n"
                portal_data["blocks"].extend(page_blocks)

        # Enough, and it already looks like contact data - stop paying for
        # further batches.
        if kept_total >= 3 and re.search(r"(地址|电话|邮箱|@|\+?\d{7,})", portal_data["text"]):
            print(f"   ⏭️  portal batches {index + 1}-{len(batches)} skipped "
                  f"({len(batches) - index} unit(s) saved)")
            break

    return portal_data


def search_cn_free_sources(company_name, country, profile, log, official_domain=""):
    """Free/accessible Chinese fallback sources, in order of trustworthiness.

    Used only when the official site did not already yield contact details.
    Every source is reached through the existing SerpAPI web search - no
    Tianyancha API, no credentials, nothing paid. Results from hosts that
    already served a wall this run are skipped without a second request.
    """
    data = {"text": "", "blocks": [], "sources": []}

    for kind, template in china_sources.CN_FALLBACK_QUERIES:
        results = serp_search(
            {
                "engine": "google",
                "q": template.format(name=company_name),
                "num": 8,
                "gl": profile["gl"],
                "hl": profile["hl"],
                "google_domain": profile["google_domain"],
            },
            f"cn fallback [{kind}]",
        )

        kept = 0
        for item in results:
            link = (item.get("link") or "").strip()
            title, snippet = item.get("title", ""), item.get("snippet", "")
            if not link or china_sources.is_blocked(link):
                continue
            # Never let a news article be a contact-detail source.
            if china_sources.is_news_source(link):
                continue
            if not result_mentions_company(company_name, link, title, snippet, country):
                continue

            # The snippet alone is often enough; only spend a page fetch when
            # it looks like the full page carries contact details.
            blob = f"{title} {snippet}"
            data["text"] += f"\n\nSOURCE: {link}\n{blob}"
            data["blocks"].extend([title, snippet])
            data["sources"].append(link)
            kept += 1

            if any(k in blob for k in ("地址", "电话", "邮箱", "联系", "法定代表人")):
                page_text, page_blocks = fetch_url_data(link, profile, timeout=8)
                if page_text:
                    data["text"] += "\n" + page_text
                    data["blocks"].extend(page_blocks)

            if kept >= 3:
                break

        if kept:
            log.ok(f"Chinese company source searched ({kind})")
        else:
            log.fail(f"No usable results from {kind} sources")

        # Stop as soon as we have something with contact-shaped content.
        if any(k in data["text"] for k in ("地址", "电话", "邮箱")):
            break

    return data


# A REAL separator is required. Making it optional let bare "法人" match
# inside words like "法人资格的境外..." and walk off with the next few
# characters ("资格的境"), which is not a name at all. "法人" alone is dropped
# for the same reason - it is a substring of too many unrelated terms.
CN_LEGAL_REP_RE = re.compile(r"(?:法定代表人|法人代表)\s*[:：]\s*([一-鿿]{2,4})")
CN_BUSINESS_RE = re.compile(r"(?:主营业务|经营范围|许可项目|一般项目)\s*[:：]\s*([^\n]{4,160})")


def build_evidence(result, corpus, profile, country):
    """Attach per-field source attribution to an otherwise-unchanged result.

    Reads only values the existing extractors already produced, then works out
    which page each one came from - so this cannot change WHAT is reported,
    only add provenance for it.
    """
    official_domain = source_domain(result.get("website") or "")
    evidence = result["evidence"]
    evidence["company_name"] = result.get("company")
    evidence["website"] = result.get("website")

    # --- phones: keep every valid distinct number, labelled where possible ---
    phones = []
    for raw in re.findall(r"\+?\d[\d\s\-().]{6,20}\d", corpus or ""):
        normalised = normalize_phone(raw, profile)
        if not normalised:
            continue
        # Product-listing pages yield digit runs that pass the country phone
        # grammar but are page artifacts (IDs, price ranges). Five identical
        # digits in a row is the giveaway; kept at five so real 400-hotline
        # style numbers still get through.
        if re.search(r"(\d)\1{4,}", normalised):
            continue
        source = china_sources.attribute(raw, corpus, official_domain)
        # A number seen only in a news article is not company contact data.
        if source and china_sources.is_news_source(source):
            continue
        phones.append({
            "value": normalised,
            "label": china_sources.label_phone(raw, corpus),
            "source": source,
        })
    if result.get("phone") and not any(p["value"] == result["phone"] for p in phones):
        phones.insert(0, {
            "value": result["phone"],
            "label": None,
            "source": china_sources.attribute(result["phone"], corpus, official_domain),
        })
    evidence["phone"] = china_sources.dedupe_entries(phones)[:6]

    # --- emails ---
    emails = [clean_email(c) for c in EMAIL_RE.findall(corpus or "")]
    emails = [c for c in emails if not any(bad in c.lower() for bad in BAD_EMAIL_HINTS)]
    if result.get("email"):
        result["email"] = clean_email(result["email"])
        emails.insert(0, result["email"])
    seen_email = []
    for value in emails:
        source = china_sources.attribute(value, corpus, official_domain)
        if source and china_sources.is_news_source(source):
            continue
        seen_email.append({"value": value, "source": source})
    evidence["email"] = china_sources.dedupe_entries(seen_email)[:5]

    # --- address: original Chinese + English translation, same values as the
    # flat fields, just with a source attached ---
    original = result.get("address_original")
    english = result.get("address")
    evidence["address"] = {
        "original": original,
        "english": english,
        "source": china_sources.attribute(original or english, corpus, official_domain),
    }

    def sourced(value, builder):
        """Attach a source, but drop the field if it only came from a news
        article - a registry fact quoted in a press piece is not provenance."""
        if not value:
            return None
        src = china_sources.attribute(value, corpus, official_domain)
        if src and china_sources.is_news_source(src):
            return None
        return builder(src)

    if country == "CN":
        match = CN_LEGAL_REP_RE.search(corpus or "")
        # Must also read as a plausible Chinese personal name, not just any
        # 2-4 characters that happened to follow the label.
        person = valid_cn_contact_person(match.group(1)) if match else None
        if person:
            evidence["legal_representative"] = sourced(person, lambda src: {
                "original": person,
                "english": romanize_person(person),
                "source": src,
            })

        match = CN_BUSINESS_RE.search(corpus or "")
        business = _li_clean(match.group(1)) if match else None
        if business:
            evidence["main_business"] = sourced(business, lambda src: {
                "original": business,
                "english": translate_cn_snippet(business) if has_cjk(business) else business,
                "source": src,
            })

    if result.get("contact_person"):
        bare = result["contact_person"].split(" (")[0]
        evidence["key_personnel"] = [e for e in [sourced(bare, lambda src: {
            "name": result["contact_person"],
            "title": result.get("designation"),
            "source": src,
        })] if e]

    evidence["blocked_sources"] = china_sources.blocked_report()
    return evidence


# ==========================================
# LINKEDIN PEOPLE RESEARCH
# ==========================================

# Country -> ordered role tiers. Tier 1 is tried first; tier 2 is used ONLY
# when tier 1 produced nothing, and the two are never mixed. Countries absent
# from this map get no LinkedIn pass at all - inventing a "relevant role" for
# them would be guesswork, and this module must never guess.
LINKEDIN_ROLE_TIERS = {
    "CN": [
        {
            "label": "Export Manager",
            "exact": ["export manager"],
            "variants": [
                "export sales manager", "international sales manager",
                "overseas sales manager", "export director",
                "export marketing manager", "foreign trade manager",
            ],
        },
        {
            "label": "Sales Manager",
            "exact": ["sales manager"],
            "variants": ["sales director", "regional sales manager", "area sales manager"],
        },
    ],
    "IN": [
        {
            "label": "Purchase Manager",
            "exact": ["purchase manager"],
            "variants": [
                "purchasing manager", "procurement manager", "purchase head",
                "procurement head", "purchase director", "procurement director",
            ],
        },
        {
            "label": "Import Manager",
            "exact": ["import manager"],
            "variants": ["import export manager", "import/export manager", "imports manager"],
        },
    ],
}

# LinkedIn serves profiles from www. and from country subdomains (cn., in.,
# uk.), so the host label must not be pinned to a fixed length.
LINKEDIN_PROFILE_RE = re.compile(r"^https?://(?:[a-z0-9-]+\.)?linkedin\.com/in/[^/?#]+", re.I)
LINKEDIN_COMPANY_RE = re.compile(r"^https?://(?:[a-z0-9-]+\.)?linkedin\.com/company/[^/?#]+", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Scraped pages run the label straight into the value ("Emailsale@x.com",
# "E-mail:info@x.com" stripped of punctuation), and the regex above happily
# swallows the label. Only strip when something sensible remains.
EMAIL_LABEL_PREFIX_RE = re.compile(r"^(?:e-?mail|mailto|mail|contact|tel|phone)(?=[a-z0-9._%+\-]{2,}@)", re.I)


def clean_email(value):
    if not value:
        return value
    cleaned = EMAIL_LABEL_PREFIX_RE.sub("", value.strip(".,;:()[]<>"))
    return cleaned or value
BAD_EMAIL_HINTS = ("example.com", "linkedin.com", "sentry.io", "noreply", "no-reply",
                   "domain.com", "email.com", "yourcompany")


def _li_clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip(" -–—|·,:")


def plausible_person_name(name):
    """A person's name, not a job label or a company string."""
    if not name:
        return False
    cleaned = _li_clean(name)
    if has_cjk(cleaned):
        return 2 <= len(re.findall(r"[一-鿿]", cleaned)) <= 6
    words = re.findall(r"[A-Za-z][A-Za-z'.\-]*", cleaned)
    if not 2 <= len(words) <= 4:
        return False
    if cleaned.lower() in GENERIC_NAMES:
        return False
    # Job titles ("Export Manager") are two capitalised words too - reject any
    # name that is actually made of role vocabulary.
    role_words = {"manager", "director", "export", "import", "sales", "purchase",
                  "purchasing", "procurement", "officer", "head", "executive",
                  "engineer", "assistant", "ltd", "limited", "company", "group"}
    return not any(w.lower() in role_words for w in words)


def parse_linkedin_person(item):
    """Split one LinkedIn SERP row into (name, title, company).

    Google renders these as "Name - Title - Company | LinkedIn", sometimes
    with the company omitted, so fall back to the snippet's usual
    "<Title> at <Company> · Experience: ..." shape.
    """
    head = re.split(r"\|", item.get("title") or "")[0]
    parts = [p for p in (_li_clean(x) for x in re.split(r"\s+[-–—]\s+", head)) if p]
    name = parts[0] if parts else None
    title = parts[1] if len(parts) > 1 else None
    company = parts[2] if len(parts) > 2 else None

    # "Export Sales Manager at xinfa wheels" arrives as one segment when the
    # SERP title uses "at" instead of a dash. Split it so the job title stays
    # a job title and the employer is captured rather than lost.
    if title and not company:
        at_split = re.split(r"\s+at\s+", title, maxsplit=1, flags=re.I)
        if len(at_split) == 2:
            title, company = _li_clean(at_split[0]), _li_clean(at_split[1])

    snippet = item.get("snippet") or ""
    if not title or not company:
        match = re.search(r"([^·•\n]{3,80}?)\s+at\s+([^·•\n]{2,80})", snippet)
        if match:
            title = title or _li_clean(match.group(1))
            # Snippets tack the location on after the employer
            # ("Xinfa Group Co., Ltd. - Shandong"); keep only the employer.
            company = company or _li_clean(re.split(r"\s+[-–—]\s+", match.group(2))[0])
    return name, title, company


def match_role_tier(title, tier):
    """Return 'exact', 'variant', or None for a candidate's ACTUAL title.

    Loosely related titles are reported as 'variant' rather than being
    silently presented as the requested role.
    """
    if not title:
        return None
    low = re.sub(r"\s+", " ", re.sub(r"[^a-z/ ]", " ", title.lower())).strip()
    # Variants are checked FIRST because they are the more specific phrase:
    # "Regional Sales Manager" contains "sales manager", so an exact-first
    # test would mislabel a listed variant as an exact-title match.
    for phrase in tier["variants"]:
        if re.search(rf"\b{re.escape(phrase)}\b", low):
            return "variant"
    for phrase in tier["exact"]:
        if re.search(rf"\b{re.escape(phrase)}\b", low):
            return "exact"
    return None


def linkedin_belongs_to_company(company_name, blob):
    """Every distinctive token of the target company must appear.

    Only safe for matching a LinkedIn *company page*, where the blob is about
    the company itself. For people, use employer_matches_company() - matching
    a person's whole SERP row lets the company name hit their own name or a
    former employer and wrongly pass.
    """
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(company_name)]
    if not tokens:
        return False
    hay = re.sub(r"[^a-z0-9]", "", (blob or "").lower())
    return all(t in hay for t in tokens)


# Distinct legal entities that merely share a brand token. "PT." (Indonesia),
# "Sdn Bhd" (Malaysia) and friends mark a separate national company, which is
# not the company the user searched for.
FOREIGN_ENTITY_MARKERS = {
    "pt.": "ID", "pt ": "ID", "indonesia": "ID", "sdn bhd": "MY", "malaysia": "MY",
    "pvt": "IN", "india": "IN", "vietnam": "VN", "thailand": "TH", "korea": "KR",
    "japan": "JP", "gmbh": "DE", "germany": "DE", "brasil": "BR", "brazil": "BR",
    "singapore": "SG", "philippines": "PH", "taiwan": "TW", "china": "CN",
}

PAST_ROLE_MARKERS = ("previously", "formerly", "former ", "ex-", "retired", "past:")


def employer_matches_company(company_name, employer, country):
    """Does this person's CURRENT employer verifiably equal the target company?

    Deliberately strict: an unparseable employer returns False. Reporting an
    unverified person as an employee is worse than returning fewer people.
    """
    if not employer:
        return False

    low = employer.lower()
    if any(marker in low for marker in PAST_ROLE_MARKERS):
        return False

    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(company_name)]
    if not tokens:
        return False
    flat = re.sub(r"[^a-z0-9]", "", low)
    if not all(t in flat for t in tokens):
        return False

    # A national sister-entity ("PT.SINOPEC INDONESIA") carries the brand token
    # but is a different company than the one searched for in this country.
    for marker, owner in FOREIGN_ENTITY_MARKERS.items():
        if marker in low and owner != country:
            return False
    return True


def extract_public_contact(blob, profile):
    """Pull an email/phone out of already-public text. Never synthesises one."""
    email = None
    for candidate in EMAIL_RE.findall(blob or ""):
        candidate = candidate.strip(".,;:()[]<>")
        if any(bad in candidate.lower() for bad in BAD_EMAIL_HINTS):
            continue
        email = candidate
        break

    phone = None
    for candidate in re.findall(r"\+?\d[\d\s\-().]{7,20}\d", blob or ""):
        phone = normalize_phone(candidate, profile)
        if phone:
            break
    return email, phone


def contact_near_name(person_name, corpus, profile, window=240):
    """Look for this person's contact details beside their name in text we
    already fetched from the company's own site.

    Costs no extra API calls, and the window stops a name being paired with an
    unrelated contact block elsewhere on the page.
    """
    if not person_name or not corpus:
        return None, None
    bare = _li_clean(person_name.split(" (")[0])
    if len(bare) < 3:
        return None, None
    for match in re.finditer(re.escape(bare), corpus, re.IGNORECASE):
        segment = corpus[max(0, match.start() - window): match.end() + window]
        email, phone = extract_public_contact(segment, profile)
        if email or phone:
            return email, phone
    return None, None


def find_linkedin_company_page(company_name, country, profile):
    results = serp_search(
        {
            "engine": "google",
            "q": f'"{company_name}" site:linkedin.com/company',
            "num": 5,
            "gl": profile["gl"],
            "hl": "en",
            "google_domain": profile["google_domain"],
        },
        "linkedin company page",
    )
    for item in results:
        link = (item.get("link") or "").strip()
        match = LINKEDIN_COMPANY_RE.match(link)
        if not match:
            continue
        blob = f"{item.get('title', '')} {item.get('snippet', '')} {link}"
        if linkedin_belongs_to_company(company_name, blob):
            return match.group(0)
    return None


def linkedin_people_queries(company_name, tier, country_label=""):
    """The searches a person would actually type, broadest first.

    Quoting every term and pinning site:linkedin.com/in makes Google demand
    literal exact matches, which misses profiles whose headline words the
    person phrased differently. Leading with the plain-language form
    ("Sinopec export manager linkedin") lets Google do the matching it is
    good at; strict employer validation downstream throws out the noise that
    a looser query lets in.
    """
    queries = [
        f"{company_name} {tier['label']} linkedin",
        f"{company_name} {tier['label']} linkedin{' ' + country_label if country_label else ''}",
    ]
    variants = tier["variants"][:3]
    if variants:
        queries.append(f"{company_name} {' OR '.join(variants)} linkedin")
    # Kept last as a precision backstop, since it is the narrowest phrasing.
    queries.append(f'"{company_name}" "{tier["label"]}" site:linkedin.com/in')
    return queries


def collect_linkedin_people(company_name, country, tier, profile, corpus=""):
    """Verified people for ONE role tier. Returns at most 3.

    Runs progressively broader searches, stopping as soon as three profiles
    pass employer validation, so the extra query shapes only cost SerpAPI
    units when the earlier ones came up short.
    """
    queries = linkedin_people_queries(company_name, tier, profile["name"])
    found, seen = [], set()

    for round_index, query in enumerate(queries):
        results = serp_search(
            {
                "engine": "google",
                "q": query,
                "num": 10,
                "gl": profile["gl"],
                "hl": "en",
                "google_domain": profile["google_domain"],
            },
            f"linkedin people [{tier['label']}{'/variants' if round_index else ''}]",
        )

        for item in results:
            link = (item.get("link") or "").strip()
            url_match = LINKEDIN_PROFILE_RE.match(link)
            if not url_match:
                continue
            profile_url = url_match.group(0)
            key = profile_url.lower().rstrip("/")
            if key in seen:
                continue

            name, title, person_company = parse_linkedin_person(item)
            if not plausible_person_name(name):
                continue

            blob = f"{item.get('title', '')} {item.get('snippet', '')}"
            # Verify against the CURRENT EMPLOYER only. Matching the whole SERP
            # row would let the company token hit the person's own name
            # ("Sinopec Mao"), a former employer ("previously Sinopec"), or a
            # separate national entity ("PT.SINOPEC INDONESIA") and pass.
            if not employer_matches_company(company_name, person_company, country):
                continue

            title_match = match_role_tier(title, tier)
            if not title_match:
                continue

            email, phone = extract_public_contact(blob, profile)
            contact_source = "LinkedIn" if (email or phone) else None
            if not (email or phone):
                # Fall back to pages already fetched from the company's own
                # site, and label the provenance so it is never mistaken for
                # something LinkedIn published.
                email, phone = contact_near_name(name, corpus, profile)
                if email or phone:
                    contact_source = "Company website"

            seen.add(key)
            found.append({
                "name": _li_clean(name),
                "title": _li_clean(title) or None,
                "title_match": title_match,
                "linkedin": profile_url,
                # Report the employer exactly as LinkedIn stated it. Never
                # substitute the searched-for company: a same-token homonym
                # ("xinfa wheels" vs "Xinfa Group") would then be displayed as
                # though the person worked at the target company.
                "company": _li_clean(person_company) or None,
                "email": email,
                "phone": phone,
                "contact_source": contact_source,
            })

        # Exact-title hits rank above variant matches; among equals, people
        # with real contact details first.
        found.sort(key=lambda p: (p["title_match"] != "exact", not (p["email"] or p["phone"])))
        if len(found) >= 3:
            return found[:3]

    return found[:3]


def research_linkedin(company_name, country, profile, corpus=""):
    """Country-driven LinkedIn pass, run after the company itself is identified.

    NOTE ON SOURCES: LinkedIn profile pages sit behind a login wall, so this
    reads only what Google has publicly indexed (title + snippet) plus company
    pages already fetched. It therefore reports far fewer emails/phones than a
    logged-in scrape would - which is the intended trade-off: everything
    returned is genuinely public, and anything unknown stays "Not Found".
    """
    tiers = LINKEDIN_ROLE_TIERS.get(country)
    if not tiers:
        return {
            "company_page": None, "role_searched": None, "fallback_used": False,
            "people": [],
            "note": f"No LinkedIn role priority is defined for {profile['name']}.",
        }

    print(f"💼 Step 4: LinkedIn ({profile['name']}) - priority role: {tiers[0]['label']}")
    data = {
        "company_page": find_linkedin_company_page(company_name, country, profile),
        "role_searched": tiers[0]["label"],
        "fallback_used": False,
        "people": [],
        "note": None,
    }

    for index, tier in enumerate(tiers):
        people = collect_linkedin_people(company_name, country, tier, profile, corpus)
        if people:
            data["role_searched"] = tier["label"]
            data["fallback_used"] = index > 0
            data["people"] = people
            print(f"   ✅ {len(people)} verified {tier['label']} profile(s)"
                  f"{' (fallback tier)' if index else ''}")
            return data
        print(f"   ⚠️ No verified {tier['label']} profiles found")

    data["note"] = "No verified profiles found for either priority role."
    return data


# ==========================================
# PIPELINE
# ==========================================

CONTACT_PATHS_EN = ["", "contact", "contact-us", "about-us", "about"]
CONTACT_PATHS_ZH = ["", "contact", "contact.html", "lxwm", "about", "gywm",
                    "contact_us.html", "lianxi"]


def research_company(company_name, country=None, industry_hint=None, use_cache=True,
                     include_linkedin=True):
    """Research one company.

    country: ISO code ("IN", "CN", ...) or country name. Mandatory in practice -
    if omitted we infer CN for CJK names and otherwise fall back to India with a
    warning, so old call sites keep working.

    include_linkedin: run the LinkedIn people pass (costs up to 5 extra SerpAPI
    units). Only CN and IN have role priorities defined; other countries skip it.
    """
    if not country:
        country = "CN" if has_cjk(company_name) else DEFAULT_COUNTRY
        print(f"⚠️ No country given - assuming {COUNTRY_PROFILES[country]['name']}. "
              f"Pass country= explicitly for reliable results.")

    country = resolve_country(country)
    profile = COUNTRY_PROFILES[country]

    if use_cache:
        cached = cache_load(company_name, country)
        if cached:
            print(f"\n💾 Cache hit: {company_name} ({profile['name']}) - 0 SerpAPI units used")
            return cached

    print(f"\n🔎 Researching: {company_name}  [{profile['name']} / +{profile['dial_code']}]")
    result = empty_result(company_name, country)

    # Blocked hosts are remembered per run, so a wall is hit at most once.
    china_sources.reset_blocked()
    log = china_sources.ResearchLog(
        "China Research" if country == "CN" else f"{profile['name']} Research")

    all_text = ""
    all_blocks = []

    # --- 1. Google, scoped to the selected country -----------------------
    print(f"🌐 Step 1: Google ({profile['gl']}/{profile['hl']}) for the official website...")
    web_results = search_web(company_name, country, industry_hint)
    official_url = pick_official_website(company_name, web_results, country)

    log.ok("General web search")

    if official_url:
        result["website"] = official_url
        print(f"✅ Official website: {official_url}")
        log.ok(f"Official website found ({source_domain(official_url)})")

        site_data = search_official_contact_pages(result["website"], profile, country)
        all_text += "\n" + site_data["text"]
        all_blocks.extend(site_data["blocks"])
        result["sources"].extend(site_data["sources"])

        # Also fetch official-domain Google results. Some Chinese corporate
        # contact information lives in annual-report/contact PDFs or pages that
        # are not linked from the homepage. These are still first-party because
        # they are hosted on the verified official domain.
        if country == "CN":
            official_domain = source_domain(result["website"])
            for item in web_results:
                link = (item.get("link") or "").strip()
                if not link or not domain_matches(source_domain(link), official_domain):
                    continue
                if link in result["sources"]:
                    continue
                page_text, page_blocks = fetch_url_data(link, profile, timeout=12)
                if page_text:
                    all_text += "\n" + page_text
                    all_blocks.extend(page_blocks)
                    result["sources"].append(link)
    else:
        print("⚠️ No official website matched this country. Using search snippets.")
        log.fail("No official website could be verified")
        for item in web_results:
            link = item.get("link", "")
            title, snippet = item.get("title", ""), item.get("snippet", "")
            if link and not result_mentions_company(company_name, link, title, snippet, country, industry_hint):
                continue  # same-prefix homonym or unrelated result - don't let it in
            # Tag with the source URL so anything extracted from this snippet
            # can be attributed back to it, instead of reporting source: null.
            all_text += (f"\nSOURCE: {link}\n{title}\n{snippet}\n" if link
                         else f"\n{title}\n{snippet}\n")
            all_blocks.extend([title, snippet])
            if link and not is_blocked_domain(link):
                result["sources"].append(link)

    # --- 2. Country-specific B2B portals, only if still thin -------------
    interim_email = extract_official_email(all_text, result["website"], company_name, country)
    interim_phone = extract_phone(all_text, profile)
    # For China, once an official website is identified, ALL contact fields
    # must come from that official domain.  Do not contaminate phone/address
    # with B2B portals or unrelated company/news pages.
    needs_portals = (not result["website"]) if country == "CN" else (not result["website"] or not (interim_email and interim_phone))

    if needs_portals:
        hosts = ", ".join(h for h in profile["portal_hosts"][:4]) or "none configured"
        print(f"🏭 Step 2: {profile['name']} B2B portals ({hosts}...)")
        portal_data = search_country_portals(company_name, country, industry_hint)
        all_text += "\n" + portal_data["text"]
        all_blocks.extend(portal_data["blocks"])
        result["sources"].extend(portal_data["sources"])
    else:
        print("⏭️  Step 2 skipped - website already yielded email + phone (1 unit saved)")

    # --- 2b. China-only free fallback sources ----------------------------
    # Runs only when the official site and portals left us without contact
    # details - so a company whose own site already answered costs nothing
    # extra here.
    if country == "CN":
        for host, reason in china_sources.blocked_report().items():
            if reason == "geo_blocked":
                log.fail(f"{host} blocked by geographic restriction")
            else:
                log.fail(f"{host} unavailable ({reason})")

        has_contact = bool(re.search(r"(地址|电话|邮箱|@)", all_text))
        if not has_contact:
            print("🇨🇳 Step 2b: free Chinese sources (registry / profiles / directories)")
            cn_data = search_cn_free_sources(company_name, country, profile, log,
                                             source_domain(result.get("website") or ""))
            all_text += "\n" + cn_data["text"]
            all_blocks.extend(cn_data["blocks"])
            result["sources"].extend(cn_data["sources"])
        else:
            log.info("Contact details already found - free-source fallback skipped")

    # --- 3. Field extraction --------------------------------------------
    result["email"] = extract_official_email(all_text, result["website"], company_name, country)
    result["phone"] = extract_phone(all_text, profile)
    result["whatsapp"] = extract_whatsapp(all_text, profile)
    result["wechat"] = extract_wechat(all_text, profile) if country == "CN" else None

    person, cn_title = extract_verified_contact_person(all_blocks, country)
    result["contact_person"] = person
    if person:
        designation_match = re.search(
            rf"(Chairman|Managing Director|Director|MD|CEO|Founder|Proprietor|Partner|General Manager)"
            rf"\s*[:\-]?\s*{re.escape(person.split(' (')[0])}",
            all_text, re.IGNORECASE,
        )
        result["designation"] = (
            designation_match.group(1) if designation_match
            else (cn_title or "Director / Executive")
        )

    city, address_en, address_zh = extract_location(all_text, profile, country)
    result["location"] = city
    result["address"] = address_en
    result["address_original"] = address_zh

    result["industry"] = extract_industry(all_text)
    result["products"] = extract_products(all_text)

    # --- 4. Preferred messenger -----------------------------------------
    # WhatsApp is effectively unusable in China, so WeChat is the fallback.
    if result["whatsapp"]:
        result["preferred_messenger"] = {"type": "whatsapp", "value": result["whatsapp"]}
    elif result["wechat"]:
        result["preferred_messenger"] = {"type": "wechat", "value": result["wechat"]}
    elif country == "CN" and result["phone"] and result["phone"].startswith("+861"):
        # Chinese mobiles are almost always the WeChat account too.
        result["wechat"] = result["phone"]
        result["preferred_messenger"] = {
            "type": "wechat", "value": result["phone"], "note": "mobile assumed to be WeChat ID",
        }

    result["sources"] = list(dict.fromkeys(result["sources"]))[:8]

    # --- 4b. Source attribution + run log --------------------------------
    log.ok("Address found") if result.get("address") else log.fail("No address found")
    if result.get("address_original") and result.get("address"):
        log.ok("Address translated")
    log.ok("Phone found") if result.get("phone") else log.fail("No phone found")
    log.ok("Email found") if result.get("email") else log.fail("No email found")

    result["evidence"] = build_evidence(result, all_text, profile, country)
    result["research_log"] = log.as_dict()

    # --- 5. LinkedIn people (country-driven role priority) ---------------
    # Runs last so it can reuse all_text - the pages already fetched from the
    # company's own site - to cross-reference contact details for free.
    if include_linkedin:
        result["linkedin"] = research_linkedin(company_name, country, profile, all_text)

    result["serpapi_units"] = Usage.calls

    cache_save(company_name, country, result)
    return result


# ==========================================
# CLI
# ==========================================

MENU_ORDER = ["IN", "CN", "US", "DE", "AE", "VN", "KR", "JP"]


def prompt_country():
    print("\nSelect the company's country (required):")
    for i, code in enumerate(MENU_ORDER, start=1):
        prof = COUNTRY_PROFILES[code]
        print(f"  {i}. {prof['name']:<20} (+{prof['dial_code']})")

    while True:
        choice = input("> ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(MENU_ORDER):
            return MENU_ORDER[int(choice) - 1]
        code = resolve_country(choice)
        if choice and code and (choice.upper() in COUNTRY_PROFILES
                                or code != DEFAULT_COUNTRY or choice.upper() == "IN"):
            return code
        print("Please enter a number from the list (or an ISO code such as CN).")


if __name__ == "__main__":
    company = input("\nEnter company name to research:\n> ").strip()
    if company:
        selected_country = prompt_country()
        hint = input("Optional industry hint (Enter to skip):\n> ").strip() or None

        data = research_company(company, country=selected_country, industry_hint=hint)
        print("\n========== FINAL COMPANY DATA ==========\n")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        print(f"\nSerpAPI units used this run: {Usage.calls}")
