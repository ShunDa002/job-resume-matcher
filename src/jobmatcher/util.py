from __future__ import annotations
import hashlib, html, json, re
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse, urlunparse

def canonical_json(data)->str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",",":"), default=str)

def sha256_data(data)->str:
    return "sha256:"+hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()

def normalize_text(value:str)->str:
    value=html.unescape(value or "")
    value=re.sub(r"<[^>]+>"," ",value)
    return re.sub(r"\s+"," ",value).strip()

def extract_url(value:str|None)->str|None:
    if not value: return None
    m=re.search(r'href=["\']([^"\']+)',value)
    raw=m.group(1) if m else value.strip()
    p=urlparse(html.unescape(raw))
    if not p.scheme or not p.netloc: return None
    return urlunparse((p.scheme,p.netloc,p.path,"","",""))

def decimal_round(value)->float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP))

def normalize_key(value:str)->str:
    return re.sub(r"[^a-z0-9]+","_",normalize_text(value).lower()).strip("_")
