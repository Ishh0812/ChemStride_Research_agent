import os
import re
import json
from urllib.parse import urljoin

from dotenv import load_dotenv
from serpapi import GoogleSearch
import requests
from bs4 import BeautifulSoup

load_dotenv()

serpapi_key = os.getenv("SERPAPI_API_KEY")

PORTAL_SITES = [
    "site:indiamart.com/company",
    "site:indiamart.com/proddetail",
    "site:zaubacorp.com/company",
    "site:justdial.com",
    "site:cphi-online.com/company"
]

# Blocked from ever being classified as the official website
BLOCKED_WEBSITE_DOMAINS = {
    "indiamart.com", "tradeindia.com", "justdial.com", "zaubacorp.com",
    "cphi-online.com", "tofler.in", "company360.in", "linkedin.com",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com",
    "business-directory", "go4worldbusiness.com", "made-in-china.com",
    "lookchem.com", "rbi.org.in", "sebi.gov.in", "mca.gov.in", "nseindia.com",
    "bseindia.com", "pinterest.com", "tracxn.com", "crunchbase.com"
}

GENERIC_NAMES = {
    "home contact us", "contact us", "about us", "investor", "investors",
    "customer care", "customer service", "supplier", "supplier mr",
    "mr", "ms", "mrs", "codes", "menu", "home", "contact", "support team",
    "sales manager", "director", "manager", "admin", "vendor", "general manager",
    "authorized signatory", "key management personnel"
}

MARKETING_WORDS = {
    "structured", "protect", "protecting", "protected", "committed",
    "helping", "quality", "trusted", "leading", "innovative", "solutions",
    "excellence", "delivering", "empowering", "building", "creating",
    "driven", "focused", "dedicated", "reliable", "sustainable", "future", "growth"
}


# ==========================================
# STRICT HELPERS & STRING NORMALIZATION
# ==========================================

def normalize_name(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def empty_result(company_name):
    return {
        "company": company_name,
        "website": None,
        "email": None,
        "phone": None,
        "whatsapp": None,
        "contact_person": None,
        "designation": None,
        "location": None,
        "industry": None,
        "products": [],
        "sources": []
    }


def source_domain(url):
    match = re.search(r"https?://(?:www\.)?([^/]+)", url or "", re.IGNORECASE)
    return match.group(1).lower() if match else ""


def same_domain(url_a, url_b):
    a, b = source_domain(url_a), source_domain(url_b)
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def decode_cf_email(cf_hex):
    try:
        k = int(cf_hex[:2], 16)
        return "".join(
            chr(int(cf_hex[i:i + 2], 16) ^ k)
            for i in range(2, len(cf_hex), 2)
        )
    except Exception:
        return ""


def is_company_owned_domain(company_name, url):
    domain = source_domain(url)
    if not domain or any(b in domain for b in BLOCKED_WEBSITE_DOMAINS):
        return False

    words = [
        w for w in normalize_name(company_name).split()
        if len(w) >= 4 and w not in {"private", "limited", "company", "corporation", "industries", "pvt", "ltd", "enterprises"}
    ]
    if not words:
        return False
    return any(re.sub(r"[^a-z0-9]", "", w) in re.sub(r"[^a-z0-9]", "", domain) for w in words)


# ==========================================
# STRICT EXTRACTION ENGINES
# ==========================================

def extract_official_email(text, official_website, company_name):
    if not text:
        return None

    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if not emails:
        return None

    official_domain = source_domain(official_website)
    company_tokens = [
        re.sub(r"[^a-z0-9]", "", w.lower())
        for w in normalize_name(company_name).split()
        if len(w) >= 4 and w not in {"private", "limited", "company", "corporation", "industries", "pvt", "ltd"}
    ]

    candidates = []
    bad_domains = ["example.com", "test.com", "domain.com", "noreply", "no-reply", "sentry.io", "indiamart.com", "justdial.com"]

    for email in emails:
        email = email.strip(".,;:()[]<>")
        lower = email.lower()

        if any(bad in lower for bad in bad_domains):
            continue

        email_domain = lower.split("@", 1)[-1]
        score = 0

        if official_domain:
            clean_official = official_domain.lower()
            if email_domain == clean_official:
                score += 100
            elif email_domain.endswith("." + clean_official):
                score += 90

        if any(token in re.sub(r"[^a-z0-9]", "", email_domain) for token in company_tokens):
            score += 50

        if any(lower.startswith(p) for p in ["sales@", "info@", "contact@", "marketing@", "enquiry@", "enquiries@", "business@"]):
            score += 10

        if score > 0 or not official_domain:
            candidates.append((score, email))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], len(x[1])))
    return candidates[0][1]


def extract_phone_from_tel_links(text):
    """Prefer phone numbers explicitly found in tel: links."""
    if not text:
        return None

    matches = re.findall(r"PHONE:\s*([^\n]+)", text, re.IGNORECASE)

    for value in matches:
        digits = re.sub(r"\D", "", value)

        if digits.startswith("91") and len(digits) == 12:
            return "+91" + digits[2:]

        if len(digits) == 10 and digits[0] in "6789":
            return "+91" + digits

    return None


def extract_whatsapp(text):
    if not text:
        return None

    patterns = [
        r"WhatsApp[\s:,-]*(\+91[\s-]?\d{5}[\s-]?\d{5})",
        r"WhatsApp[\s:,-]*(\+91[\s-]?\d{10})",
        r"WhatsApp[\s:,-]*(\b[6-9]\d{9}\b)",
        r"whatsapp\.com/send\?phone=(\d{10,15})",
        r"wa\.me/(\d{10,15})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            number = re.sub(r"\D", "", match.group(1))
            if number.startswith("91") and len(number) == 12:
                return "+" + number
            if len(number) == 10:
                return "+91" + number
            return "+" + number
    return None

STOP_WORDS = {
    "and", "or", "the", "in", "on", "at", "by", "for", "with", "about",
    "handled", "handling", "services", "solutions", "products", "team",
    "management", "board", "regulatory", "documentation", "compliance",
    "quality", "assurance", "operations", "business", "global", "office",
    "pvt", "ltd", "limited", "company", "chemstride", "stride", "chemical"
}

def valid_contact_person(name):
    if not name:
        return None

    cleaned = re.sub(r"\s+", " ", name.replace("\\n", " ")).strip()
    words = re.findall(r"[A-Za-z]+", cleaned)
    
    # Must be standard 2-3 word human name (First Last or First Middle Last)
    if not 2 <= len(words) <= 3:
        return None

    # Reject if any token is a common English stop word, verb, or generic label
    for w in words:
        w_lower = w.lower()
        if w_lower in STOP_WORDS or w_lower in GENERIC_NAMES or w_lower in MARKETING_WORDS:
            return None
        # Reject common verb past-tenses / gerunds
        if w_lower.endswith(("ed", "ing", "tion", "sion", "ment", "ance")):
            return None

    return " ".join(w.capitalize() for w in words)

def extract_verified_contact_person(blocks):
    if not blocks:
        return None

    # Enforce strict capitalization and structural markers only (e.g., "Director: John Doe")
    patterns = [
        r"(?:Director|Managing Director|MD|CEO|Founder|Proprietor|Key Person)\s*[:\-]\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:Contact Person|Contact Name)\s*[:\-]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
        r"\b(?:Mr\.?|Ms\.?|Mrs\.?)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\b"
    ]

    for block in blocks:
        for pattern in patterns:
            match = re.search(pattern, block)
            if match:
                candidate = valid_contact_person(match.group(1))
                if candidate:
                    return candidate
    return None


def extract_official_location(text):
    if not text:
        return None

    locations = [
        "Mumbai", "Delhi", "Ahmedabad", "Pune", "Bengaluru", "Bangalore",
        "Chennai", "Hyderabad", "Kolkata", "Surat", "Vadodara", "Noida",
        "Gurugram", "Gurgaon", "Rajkot", "Indore", "Jaipur", "Nashik",
        "Nagpur", "Faridabad", "Ludhiana", "Coimbatore", "Kanpur", "Thane",
        "Navi Mumbai", "Ankleshwar", "Vapi", "Secunderabad", "Baddi"
    ]

    contexts = re.findall(
        r"(?:registered office|corporate office|head office|headquarters|address|location|ROC|city|based in)[^\n]{0,200}",
        text,
        re.IGNORECASE
    )

    for context in contexts:
        for city in locations:
            if re.search(rf"\b{re.escape(city)}\b", context, re.IGNORECASE):
                return city
    return None


def extract_official_industry(text):
    if not text:
        return None

    # Ranked by specificity: Specific niches > General categories
    industry_rules = [
        ("Chemical Distribution & Trading", [
            r"\bchemical distribution\b", r"\bchemical distributor\b",
            r"\bdistributor of chemicals\b", r"\bchemical indenting\b",
            r"\bchemical trading\b", r"\bspecialty chemicals distribution\b"
        ]),
        ("Chemical Manufacturing & Specialty Chemicals", [
            r"\bchemical manufacturing\b", r"\bspecialty chemicals\b",
            r"\bperformance chemicals\b", r"\bindustrial chemicals\b"
        ]),
        ("Active Pharmaceutical Ingredients (API)", [
            r"\bapi manufacturing\b", r"\bactive pharmaceutical ingredient\b",
            r"\bbulk drug manufacturer\b"
        ]),
        ("Pharmaceuticals", [
            r"\bpharmaceutical formulation\b", r"\bpharma company\b",
            r"\bfinished dosage\b", r"\bpharmaceutical manufacturer\b"
        ]),
        ("Polymers & Plastic Raw Materials", [
            r"\bpolymer distribution\b", r"\bpolymer manufacturer\b",
            r"\bplastic raw material\b", r"\bmasterbatches\b"
        ]),
        ("Pipes & Fittings Manufacturing", [
            r"\bpvc pipes?\b", r"\bcpvc pipes?\b", r"\bhdpe pipes?\b",
            r"\bpipe manufacturing\b"
        ]),
        ("Packaging Materials", [
            r"\bpackaging solutions\b", r"\bpet preforms?\b",
            r"\bbopp bags?\b", r"\bflexible packaging\b"
        ])
    ]

    for industry_name, patterns in industry_rules:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return industry_name

    return None


def extract_official_products(text):
    if not text:
        return []

    product_keywords = [
        "API", "Active Pharmaceutical Ingredients", "Intermediates", "Formulations",
        "Bulk Drugs", "Pellets", "PVC pipes", "PVC fittings", "CPVC pipes", 
        "HDPE pipes", "PP woven bags", "PET bottles", "PET preforms", "Plastic packaging",
        "Packaging Films", "Specialty Chemicals", "Industrial Valves"
    ]

    found = []
    for p in product_keywords:
        if re.search(rf"\b{re.escape(p)}\b", text, re.IGNORECASE):
            found.append(p)
    return list(dict.fromkeys(found))[:10]


# ==========================================
# FETCH & PARSE ENGINE
# ==========================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

def extract_text_blocks(soup):
    block_tags = ["p", "li", "span", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "a"]
    blocks = []
    for tag in soup.find_all(block_tags):
        if tag.find(block_tags):
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
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if email:
                collected_text.append(f"EMAIL: {email}")
        elif href.lower().startswith("tel:"):
            phone = href[4:].strip()
            if phone:
                collected_text.append(f"PHONE: {phone}")
        elif "wa.me/" in href.lower() or "whatsapp.com" in href.lower():
            collected_text.append(f"WHATSAPP: {href}")

    collected_blocks.extend(extract_text_blocks(soup))

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    if text:
        collected_text.append(f"\nSOURCE: {url}\n{text}")

    return "\n".join(collected_text), collected_blocks


def fetch_url_data(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=8)
        if response.status_code == 200:
            return parse_page_content(response.text, url)
    except requests.RequestException:
        pass
    return "", []


# ==========================================
# WATERFALL RESEARCH PIPELINE
# ==========================================

def search_b2b_portals(company_name):
    portal_data = {"text": "", "blocks": [], "sources": []}
    
    query = f'"{company_name}" ({ " OR ".join(PORTAL_SITES) })'
    search = GoogleSearch({
        "engine": "google",
        "q": query,
        "num": 6,
        "api_key": serpapi_key
    })
    
    results = search.get_dict().get("organic_results", [])
    for item in results:
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        
        if any(portal in link for portal in ["indiamart.com", "zaubacorp.com", "justdial.com", "cphi-online.com"]):
            portal_data["sources"].append(link)
            portal_data["text"] += f"\nPORTAL_DATA ({link}):\n{title}\n{snippet}\n"
            portal_data["blocks"].extend([title, snippet])
            
            p_text, p_blocks = fetch_url_data(link)
            if p_text:
                portal_data["text"] += f"\n{p_text}\n"
                portal_data["blocks"].extend(p_blocks)

    return portal_data


def research_company(company_name):
    print(f"\n🔎 Researching: {company_name}")
    result = empty_result(company_name)

    all_text = ""
    all_blocks = []

    # -------------------------------------------------------------
    # 1. Broad Web Search (Priority: Official Web Presence)
    # -------------------------------------------------------------
    print("🌐 Step 1: Performing Broad Web Search for Official Website...")
    query = f'"{company_name}" official website company contact email phone'
    search = GoogleSearch({
        "engine": "google",
        "q": query,
        "num": 8,
        "api_key": serpapi_key
    })
    
    web_results = search.get_dict().get("organic_results", [])
    candidate_urls = [
        item.get("link", "").strip() for item in web_results
        if item.get("link") and is_company_owned_domain(company_name, item.get("link"))
    ]

    official_url = sorted(list(dict.fromkeys(candidate_urls)), key=len)[0] if candidate_urls else None

    if official_url:
        result["website"] = re.search(r"(https?://(?:www\.)?[^/]+)", official_url, re.IGNORECASE).group(1).rstrip("/")
        print(f"✅ Found Official Website: {result['website']}")

        for sub_path in ["", "contact", "contact-us", "about-us"]:
            target_url = urljoin(result["website"] + "/", sub_path)
            t, b = fetch_url_data(target_url)
            all_text += "\n" + t
            all_blocks.extend(b)
            if t:
                result["sources"].append(target_url)
    else:
        print("⚠️ No dedicated official website detected. Adding general search snippets.")
        for item in web_results:
            all_text += f"\n{item.get('title', '')}\n{item.get('snippet', '')}\n"
            all_blocks.extend([item.get('title', ''), item.get('snippet', '')])
            if item.get("link"):
                result["sources"].append(item.get("link"))

    # -------------------------------------------------------------
    # 2. Portal Search (Fallback if no website OR enrichment)
    # -------------------------------------------------------------
    needs_enrichment = not result["website"] or not (result["phone"] and result["email"])
    if needs_enrichment:
        print("🏭 Step 2: Querying B2B Portals (IndiaMART, ZaubaCorp, Justdial, CPhI)...")
        b2b_data = search_b2b_portals(company_name)
        all_text += "\n" + b2b_data["text"]
        all_blocks.extend(b2b_data["blocks"])
        result["sources"].extend(b2b_data["sources"])

    # -------------------------------------------------------------
    # 3. Parse and Normalize Fields
    # -------------------------------------------------------------
    result["email"] = extract_official_email(all_text, result["website"], company_name)
    result["phone"] = extract_phone_from_tel_links(all_text)
    result["whatsapp"] = extract_whatsapp(all_text)
    result["contact_person"] = extract_verified_contact_person(all_blocks)

    if result["contact_person"]:
        designation_match = re.search(
            rf"(Chairman|Managing Director|Director|MD|CEO|Founder|Proprietor|Partner)\s*[:\-]?\s*{re.escape(result['contact_person'])}",
            all_text,
            re.IGNORECASE
        )
        result["designation"] = designation_match.group(1) if designation_match else "Director / Executive"

    result["location"] = extract_official_location(all_text)
    result["industry"] = extract_official_industry(all_text)
    result["products"] = extract_official_products(all_text)

    # Clean sources
    result["sources"] = list(dict.fromkeys(result["sources"]))[:8]

    return result


if __name__ == "__main__":
    company = input("\nEnter company name to research:\n> ").strip()
    if company:
        result = research_company(company)
        print("\n========== FINAL COMPANY DATA ==========\n")
        print(json.dumps(result, indent=4, ensure_ascii=False))