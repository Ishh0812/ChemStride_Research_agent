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
from urllib.parse import urljoin

from dotenv import load_dotenv
from serpapi import GoogleSearch
import requests
from bs4 import BeautifulSoup

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_API_KEY")

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".research_cache.json")
CACHE_TTL_DAYS = 14

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
        "portals": [
            "site:made-in-china.com",
            "site:chemicalbook.com",
            "site:guidechem.com",
            "site:echemi.com",
            "site:molbase.com",
            "site:lookchem.com",
            "site:chemnet.com",
            "site:qcc.com",
        ],
        "portal_hosts": [
            "made-in-china.com", "chemicalbook.com", "guidechem.com", "echemi.com",
            "molbase.com", "lookchem.com", "chemnet.com", "qcc.com", "1688.com",
            "hc360.com", "gongchang.com", "tianyancha.com",
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
}

LEGAL_SUFFIXES = {
    "private", "limited", "company", "corporation", "corp", "industries",
    "pvt", "ltd", "llp", "inc", "enterprises", "group", "holdings", "co",
    "gmbh", "ag", "sa", "bv", "srl", "plc", "llc", "trading", "international",
    "technology", "technologies", "chemical", "chemicals",
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
    }


# ==========================================
# CACHE  (re-running a company costs 0 SerpAPI units)
# ==========================================

def _cache_key(company_name, country):
    raw = f"{country}|{normalize_name(company_name) or company_name}"
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
    """Return E.164 for the selected country, or None if it does not fit."""
    if not raw:
        return None

    cc = profile["dial_code"]
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None

    if digits.startswith("00" + cc):
        digits = digits[2 + len(cc):]
    elif digits.startswith(cc) and len(digits) > profile["nsn_len"][1]:
        digits = digits[len(cc):]

    while digits.startswith("0"):
        digits = digits[1:]

    lo, hi = profile["nsn_len"]
    if not (lo <= len(digits) <= hi):
        return None

    for pattern in profile["phone_patterns"]:
        if re.fullmatch(pattern, digits):
            return "+" + cc + digits
    return None


def extract_phone(text, profile):
    """tel: links first, then free text - always validated against the country."""
    if not text:
        return None

    for value in re.findall(r"PHONE:\s*([^\n]+)", text, re.IGNORECASE):
        phone = normalize_phone(value, profile)
        if phone:
            return phone

    candidates = re.findall(
        r"(?:\+?\d[\d\s\-\(\)]{7,18}\d)",
        text.replace("‐", "-").replace("–", "-"),
    )
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
    r"(?:registered office|corporate office|head office|headquarters|address|"
    r"location|ROC|factory|plant|based in)[^\n]{0,220}"
)
ADDRESS_CONTEXT_ZH = r"(?:地址|地 址|公司地址|注册地址|办公地址|厂址)[^\n]{0,120}"


def extract_location(text, profile, country):
    """Return (english_city, english_address, original_address)."""
    if not text:
        return None, None, None

    city = None
    address_raw = None

    if country == "CN":
        zh_hits = re.findall(ADDRESS_CONTEXT_ZH, text)
        if zh_hits:
            address_raw = re.sub(r"^(地址|地 址|公司地址|注册地址|办公地址|厂址)\s*[:：]?\s*", "", zh_hits[0]).strip()
        for zh, en in sorted(CN_CITY.items(), key=lambda kv: -len(kv[0])):
            if zh in text:
                city = en
                break

    contexts = re.findall(ADDRESS_CONTEXT_EN, text, re.IGNORECASE)
    if not address_raw and contexts:
        address_raw = re.sub(
            r"^(registered office|corporate office|head office|headquarters|address|location|factory|plant)\s*[:\-]?\s*",
            "", contexts[0], flags=re.IGNORECASE,
        ).strip()

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


def fetch_url_data(url, profile, timeout=8):
    try:
        response = requests.get(url, headers=build_headers(profile), timeout=timeout)
        if response.status_code == 200:
            if not response.encoding or response.encoding.lower() == "iso-8859-1":
                response.encoding = response.apparent_encoding
            return parse_page_content(response.text, url)
    except requests.RequestException:
        pass
    return "", []


# ==========================================
# WEBSITE IDENTIFICATION (country-aware)
# ==========================================

def score_website_candidate(company_name, url, title, snippet, country):
    """Higher is better. <= 0 means "not their official site"."""
    domain = source_domain(url)
    if not domain or is_blocked_domain(url):
        return -1

    profile = COUNTRY_PROFILES[country]
    flat_domain = re.sub(r"[^a-z0-9]", "", domain)
    score = 0

    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in name_tokens(company_name)]
    if tokens:
        hits = sum(1 for t in tokens if t in flat_domain)
        if hits:
            score += 60 + 10 * (hits - 1)

    # CJK company names never appear in a domain: fall back to title matching.
    if has_cjk(company_name):
        core = re.sub(r"(有限公司|股份有限公司|集团|公司)$", "", company_name.strip())
        if core and (core in (title or "") or core in (snippet or "")):
            score += 55
        if lazy_pinyin:
            py = "".join(lazy_pinyin(core))
            if len(py) >= 5 and py in flat_domain:
                score += 45

    # Country signal: local TLD is strong evidence, wrong-country TLD is a penalty.
    if any(domain.endswith(t) for t in profile["tld_bonus"]):
        score += 25
    foreign_tlds = {
        ".ca": "CA", ".co.uk": "GB", ".uk": "GB", ".au": "AU", ".ru": "RU",
        ".br": "BR", ".fr": "FR", ".it": "IT", ".es": "ES", ".mx": "MX",
        ".pl": "PL", ".nl": "NL", ".se": "SE", ".ch": "CH", ".at": "AT",
        ".za": "ZA", ".ng": "NG", ".ke": "KE", ".th": "TH", ".my": "MY",
        ".id": "ID", ".ph": "PH", ".pk": "PK", ".bd": "BD", ".lk": "LK",
        ".ir": "IR", ".sa": "SA", ".eg": "EG", ".tr": "TR", ".il": "IL",
        ".cn": "CN", ".com.cn": "CN", ".in": "IN", ".co.in": "IN",
        ".de": "DE", ".ae": "AE", ".vn": "VN", ".com.vn": "VN",
        ".kr": "KR", ".co.kr": "KR", ".jp": "JP", ".co.jp": "JP",
    }
    for tld, owner in sorted(foreign_tlds.items(), key=lambda kv: -len(kv[0])):
        if domain.endswith(tld):
            if owner != country:
                score -= 80   # a foreign ccTLD must never beat a neutral .com
            break

    # Explicit country mention in the result text.
    blob = f"{title or ''} {snippet or ''}"
    if re.search(rf"\b{re.escape(profile['name'])}\b", blob, re.IGNORECASE):
        score += 15
    if country == "CN" and has_cjk(blob):
        score += 10

    # Prefer short root domains over deep vendor subpages.
    score -= min(len(domain) // 12, 3)
    return score


def pick_official_website(company_name, results, country):
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

    if not best:
        return None
    match = re.search(r"(https?://(?:www\.)?[^/]+)", best, re.IGNORECASE)
    return match.group(1).rstrip("/") if match else None


# ==========================================
# SEARCH LAYER (country-scoped)
# ==========================================

def build_web_query(company_name, country, industry_hint=None):
    profile = COUNTRY_PROFILES[country]
    hint = f" {industry_hint}" if industry_hint else ""
    if profile["query_lang"] == "zh":
        return f'"{company_name}"{hint} 官网 公司 联系方式 邮箱 电话'
    return f'"{company_name}"{hint} {profile["name"]} official website company contact email phone'


def search_web(company_name, country, industry_hint=None, num=8):
    profile = COUNTRY_PROFILES[country]
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


def search_country_portals(company_name, country):
    """One portal query, restricted to that country's portal set."""
    profile = COUNTRY_PROFILES[country]
    portal_data = {"text": "", "blocks": [], "sources": []}

    if not profile["portals"]:
        return portal_data

    query = f'"{company_name}" ({" OR ".join(profile["portals"])})'
    results = serp_search(
        {
            "engine": "google",
            "q": query,
            "num": 6,
            "gl": profile["gl"],
            "hl": profile["hl"],
            "google_domain": profile["google_domain"],
        },
        f"portal search ({profile['name']})",
    )

    for item in results:
        link = item.get("link", "")
        if not any(host in link for host in profile["portal_hosts"]):
            continue

        title = item.get("title", "")
        snippet = item.get("snippet", "")
        portal_data["sources"].append(link)
        portal_data["text"] += f"\nPORTAL_DATA ({link}):\n{title}\n{snippet}\n"
        portal_data["blocks"].extend([title, snippet])

        page_text, page_blocks = fetch_url_data(link, profile, timeout=8)
        if page_text:
            portal_data["text"] += f"\n{page_text}\n"
            portal_data["blocks"].extend(page_blocks)

    return portal_data


# ==========================================
# PIPELINE
# ==========================================

CONTACT_PATHS_EN = ["", "contact", "contact-us", "about-us", "about"]
CONTACT_PATHS_ZH = ["", "contact", "contact.html", "lxwm", "about", "gywm",
                    "contact_us.html", "lianxi"]


def research_company(company_name, country=None, industry_hint=None, use_cache=True):
    """Research one company.

    country: ISO code ("IN", "CN", ...) or country name. Mandatory in practice -
    if omitted we infer CN for CJK names and otherwise fall back to India with a
    warning, so old call sites keep working.
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

    all_text = ""
    all_blocks = []

    # --- 1. Google, scoped to the selected country -----------------------
    print(f"🌐 Step 1: Google ({profile['gl']}/{profile['hl']}) for the official website...")
    web_results = search_web(company_name, country, industry_hint)
    official_url = pick_official_website(company_name, web_results, country)

    if official_url:
        result["website"] = official_url
        print(f"✅ Official website: {official_url}")

        paths = CONTACT_PATHS_ZH if country == "CN" else CONTACT_PATHS_EN
        for sub_path in paths:
            target_url = urljoin(result["website"] + "/", sub_path)
            page_text, page_blocks = fetch_url_data(target_url, profile)
            if page_text:
                all_text += "\n" + page_text
                all_blocks.extend(page_blocks)
                result["sources"].append(target_url)
    else:
        print("⚠️ No official website matched this country. Using search snippets.")
        for item in web_results:
            all_text += f"\n{item.get('title', '')}\n{item.get('snippet', '')}\n"
            all_blocks.extend([item.get("title", ""), item.get("snippet", "")])
            if item.get("link") and not is_blocked_domain(item["link"]):
                result["sources"].append(item["link"])

    # --- 2. Country-specific B2B portals, only if still thin -------------
    interim_email = extract_official_email(all_text, result["website"], company_name, country)
    interim_phone = extract_phone(all_text, profile)
    needs_portals = not result["website"] or not (interim_email and interim_phone)

    if needs_portals:
        hosts = ", ".join(h for h in profile["portal_hosts"][:4]) or "none configured"
        print(f"🏭 Step 2: {profile['name']} B2B portals ({hosts}...)")
        portal_data = search_country_portals(company_name, country)
        all_text += "\n" + portal_data["text"]
        all_blocks.extend(portal_data["blocks"])
        result["sources"].extend(portal_data["sources"])
    else:
        print("⏭️  Step 2 skipped - website already yielded email + phone (1 unit saved)")

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
