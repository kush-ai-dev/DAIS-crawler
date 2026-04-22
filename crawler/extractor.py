"""
DAIS Crawler - SEO Extraction Engine
Runs 50+ checks on a single fetched page's HTML + metadata.
"""

import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

@dataclass
class SEOIssue:
    check: str
    severity: str          # critical | warning | info
    message: str
    value: str = ""        # what was found (or empty if missing)
    recommendation: str = ""


@dataclass
class PageReport:
    url: str
    status_code: int
    rendered_via: str      # "http" | "playwright"
    load_time_ms: int
    page_size_kb: float

    # On-page
    title: Optional[str] = None
    title_length: int = 0
    meta_description: Optional[str] = None
    meta_description_length: int = 0
    h1_tags: list = field(default_factory=list)
    h2_count: int = 0
    h3_count: int = 0
    canonical_url: Optional[str] = None
    robots_meta: Optional[str] = None
    lang_attr: Optional[str] = None
    word_count: int = 0
    paragraph_count: int = 0

    # Links
    internal_links: int = 0
    external_links: int = 0
    internal_link_urls: list = field(default_factory=list)
    broken_link_candidates: list = field(default_factory=list)  # hrefs that 404

    # Images
    total_images: int = 0
    images_missing_alt: int = 0
    images_missing_alt_urls: list = field(default_factory=list)

    # Technical
    is_https: bool = False
    has_viewport_meta: bool = False
    has_schema_markup: bool = False
    schema_count: int = 0
    schema_types: list = field(default_factory=list)
    schemas: list = field(default_factory=list)
    schema_validation_issues: list = field(default_factory=list)
    microdata_types: list = field(default_factory=list)
    rdfa_types: list = field(default_factory=list)
    has_open_graph: bool = False
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    has_twitter_card: bool = False
    has_hreflang: bool = False

    # Performance proxies
    render_blocking_scripts: int = 0
    has_gzip: bool = False
    has_cache_headers: bool = False
    has_lazy_loading: bool = False

    # Security
    security_headers: dict = field(default_factory=dict)
    mixed_content_count: int = 0

    # Content quality
    has_thin_content: bool = False
    generic_anchor_count: int = 0
    duplicate_title: bool = False      # set externally during aggregation
    duplicate_meta: bool = False       # set externally during aggregation

    # Scoring
    severity_score: int = 100          # starts at 100, deductions applied
    issues: list = field(default_factory=list)


# ─────────────────────────────────────────────
# Severity scoring weights
# ─────────────────────────────────────────────

DEDUCTIONS = {
    "missing_title":             ("critical", 20),
    "title_too_long":            ("warning",   5),
    "title_too_short":           ("warning",   5),
    "missing_meta_description":  ("warning",   8),
    "meta_description_too_long": ("warning",   4),
    "missing_h1":                ("critical", 12),
    "multiple_h1":               ("warning",   6),
    "missing_canonical":         ("warning",   6),
    "noindex_detected":          ("critical", 15),
    "missing_viewport":          ("critical", 10),
    "not_https":                 ("critical", 20),
    "missing_open_graph":        ("info",      2),
    "missing_schema":            ("info",      3),
    "thin_content":              ("warning",   7),
    "images_missing_alt":        ("warning",   5),
    "render_blocking_scripts":   ("warning",   5),
    "missing_cache_headers":     ("info",      3),
    "mixed_content":             ("critical", 10),
    "generic_anchors":           ("info",      2),
    "missing_lang":              ("warning",   4),
    "missing_twitter_card":      ("info",      1),
    "missing_security_headers":  ("warning",   5),
}


# ─────────────────────────────────────────────
# Main Extraction Function
# ─────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Schema helper — lives at module level so it can be referenced inside extract_seo_data
# ─────────────────────────────────────────────────────────────────────────────

def _extract_schema_item(item, block_idx, top_context, parsed_schemas,
                         schema_val_issues, report, parse_fn, id_map):
    """
    Parse one schema node (from @graph or standalone),
    build the structured entry, and append to parsed_schemas.
    """
    schema_type = item.get("@type", "Unknown")
    types = [schema_type] if isinstance(schema_type, str) else (schema_type or ["Unknown"])
    context = item.get("@context", top_context)
    schema_id = item.get("@id", "")

    # Build the full parsed entry
    parsed_node = parse_fn(item, depth=0)

    entry = {
        "block_index":    block_idx,
        "type":           schema_type,
        "id":             schema_id,
        "context":        context,
        "fields":         parsed_node.get("fields", {}),
        "validation":     parsed_node.get("validation", []),
        "raw":            item,          # full original object
    }

    # Roll up validation issues
    for v in entry["validation"]:
        schema_val_issues.append({
            "block_index":  block_idx,
            "schema_type":  schema_type,
            "severity":     v["severity"],
            "issue":        v["issue"],
            "message":      v["message"],
        })

    # Add type(s) to top-level schema_types list
    for t in types:
        if t not in report.schema_types:
            report.schema_types.append(t)

    parsed_schemas.append(entry)

def extract_seo_data(
    url: str,
    html: str,
    status_code: int,
    response_headers: dict,
    load_time_ms: int,
    page_size_kb: float,
    rendered_via: str = "http",
) -> PageReport:

    soup = BeautifulSoup(html, "lxml")
    parsed_url = urlparse(url)
    base_domain = parsed_url.netloc

    report = PageReport(
        url=url,
        status_code=status_code,
        rendered_via=rendered_via,
        load_time_ms=load_time_ms,
        page_size_kb=page_size_kb,
        is_https=parsed_url.scheme == "https",
    )

    issues = []

    def add_issue(check: str, message: str, value: str = "", recommendation: str = ""):
        severity, deduction = DEDUCTIONS.get(check, ("info", 0))
        report.severity_score = max(0, report.severity_score - deduction)
        issues.append(SEOIssue(
            check=check,
            severity=severity,
            message=message,
            value=value,
            recommendation=recommendation,
        ))

    # ── HTTPS ──────────────────────────────────────────────────────────
    if not report.is_https:
        add_issue("not_https", "Page is served over HTTP, not HTTPS",
                  recommendation="Redirect all traffic to HTTPS and install a valid SSL certificate.")

    # ── TITLE ──────────────────────────────────────────────────────────
    title_tag = soup.find("title")
    if title_tag:
        report.title = title_tag.get_text(strip=True)
        report.title_length = len(report.title)
        if report.title_length > 60:
            add_issue("title_too_long", f"Title tag is {report.title_length} chars (max 60)",
                      value=report.title,
                      recommendation="Shorten the title to under 60 characters to avoid truncation in SERPs.")
        elif report.title_length < 30:
            add_issue("title_too_short", f"Title tag is only {report.title_length} chars",
                      value=report.title,
                      recommendation="Expand the title to 30–60 characters for better keyword coverage.")
    else:
        add_issue("missing_title", "Page has no <title> tag",
                  recommendation="Add a unique, descriptive title tag between 30–60 characters.")

    # ── META DESCRIPTION ───────────────────────────────────────────────
    meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta_desc and meta_desc.get("content"):
        report.meta_description = meta_desc["content"].strip()
        report.meta_description_length = len(report.meta_description)
        if report.meta_description_length > 160:
            add_issue("meta_description_too_long",
                      f"Meta description is {report.meta_description_length} chars (max 160)",
                      value=report.meta_description,
                      recommendation="Trim the meta description to under 160 characters.")
    else:
        add_issue("missing_meta_description", "Page has no meta description",
                  recommendation="Add a compelling meta description between 120–160 characters.")

    # ── HEADINGS ───────────────────────────────────────────────────────
    h1_tags = soup.find_all("h1")
    report.h1_tags = [h.get_text(strip=True) for h in h1_tags]
    report.h2_count = len(soup.find_all("h2"))
    report.h3_count = len(soup.find_all("h3"))

    if len(h1_tags) == 0:
        add_issue("missing_h1", "Page has no H1 tag",
                  recommendation="Add a single H1 tag containing your primary keyword.")
    elif len(h1_tags) > 1:
        add_issue("multiple_h1", f"Page has {len(h1_tags)} H1 tags",
                  value=str(report.h1_tags),
                  recommendation="Consolidate to a single H1 tag per page.")

    # ── CANONICAL ──────────────────────────────────────────────────────
    canonical = soup.find("link", rel=lambda r: r and "canonical" in r)
    if canonical:
        report.canonical_url = canonical.get("href", "")
    else:
        add_issue("missing_canonical", "No canonical tag found",
                  recommendation="Add a <link rel='canonical' href='...'> tag to signal the preferred URL.")

    # ── ROBOTS META ────────────────────────────────────────────────────
    robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if robots_meta:
        report.robots_meta = robots_meta.get("content", "")
        if "noindex" in report.robots_meta.lower():
            add_issue("noindex_detected", "Page is set to noindex — search engines will not index it",
                      value=report.robots_meta,
                      recommendation="Remove 'noindex' from the robots meta tag if this page should be indexed.")

    # ── VIEWPORT ───────────────────────────────────────────────────────
    viewport = soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    report.has_viewport_meta = viewport is not None
    if not report.has_viewport_meta:
        add_issue("missing_viewport", "No viewport meta tag — page may not be mobile-friendly",
                  recommendation="Add <meta name='viewport' content='width=device-width, initial-scale=1'>")

    # ── LANG ATTR ──────────────────────────────────────────────────────
    html_tag = soup.find("html")
    if html_tag:
        report.lang_attr = html_tag.get("lang")
    if not report.lang_attr:
        add_issue("missing_lang", "HTML tag has no lang attribute",
                  recommendation="Add lang attribute to <html> tag e.g. <html lang='en'>")

    # ── OPEN GRAPH ─────────────────────────────────────────────────────
    og_title = soup.find("meta", property="og:title")
    og_desc  = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")

    report.og_title       = og_title["content"] if og_title else None
    report.og_description = og_desc["content"]  if og_desc  else None
    report.og_image       = og_image["content"] if og_image else None
    report.has_open_graph = bool(og_title or og_desc or og_image)

    if not report.has_open_graph:
        add_issue("missing_open_graph", "No Open Graph tags found",
                  recommendation="Add og:title, og:description, og:image for better social sharing previews.")

    # ── TWITTER CARD ───────────────────────────────────────────────────
    twitter_card = soup.find("meta", attrs={"name": re.compile("^twitter:card$", re.I)})
    report.has_twitter_card = twitter_card is not None
    if not report.has_twitter_card:
        add_issue("missing_twitter_card", "No Twitter Card meta tags found",
                  recommendation="Add <meta name='twitter:card' content='summary_large_image'>")

    # ── SCHEMA MARKUP — Full @graph, nested objects, @id resolution ─
    import json as _json

    # ── Required fields per schema type ──────────────────────────────
    REQUIRED_FIELDS = {
        "Organization":        ["name", "url"],
        "LocalBusiness":       ["name", "address", "telephone"],
        "WebSite":             ["name", "url"],
        "WebPage":             ["name", "url"],
        "Article":             ["headline", "author", "datePublished", "image"],
        "BlogPosting":         ["headline", "author", "datePublished", "image"],
        "NewsArticle":         ["headline", "author", "datePublished", "image"],
        "Product":             ["name", "image", "description", "offers"],
        "Review":              ["reviewRating", "author", "itemReviewed"],
        "FAQPage":             ["mainEntity"],
        "HowTo":               ["name", "step"],
        "BreadcrumbList":      ["itemListElement"],
        "Person":              ["name"],
        "Event":               ["name", "startDate", "location"],
        "JobPosting":          ["title", "description", "datePosted", "hiringOrganization"],
        "Recipe":              ["name", "recipeIngredient", "recipeInstructions"],
        "VideoObject":         ["name", "description", "thumbnailUrl", "uploadDate"],
        "Course":              ["name", "description", "provider"],
        "SoftwareApplication": ["name", "operatingSystem", "applicationCategory"],
        "Service":             ["name", "provider"],
        "ImageObject":         ["url", "width", "height"],
        "BreadcrumbList":      ["itemListElement"],
        "SearchAction":        ["target", "query-input"],
    }

    def _flatten_value(val, depth=0):
        """
        Recursively flatten a schema value into a human-readable structure.
        Mirrors what validator.schema.org displays — walks into nested dicts/lists.
        Resolves @id-only reference nodes against the id_registry.
        """
        if depth > 8:
            return val  # safety cap on recursion
        if isinstance(val, dict):
            # Pure @id reference node — resolve it from registry
            if list(val.keys()) == ["@id"]:
                ref = val["@id"]
                resolved = id_registry.get(ref)
                if resolved:
                    return _flatten_value(resolved, depth + 1)
                return {"@id": ref, "_note": "referenced object defined elsewhere in graph"}
            result = {}
            for k, v in val.items():
                result[k] = _flatten_value(v, depth + 1)
            return result
        elif isinstance(val, list):
            return [_flatten_value(i, depth + 1) for i in val]
        else:
            return val

    def _validate_schema_node(node, block_index, id_registry):
        """
        Validate a single schema node dict.
        Returns (schema_entry, list_of_issues)
        """
        schema_type = node.get("@type", "Unknown")
        schema_id   = node.get("@id", "")
        context     = node.get("@context", "")

        # Normalize type — can be string or list (e.g. ["Organization","LocalBusiness"])
        types = [schema_type] if isinstance(schema_type, str) else (schema_type if isinstance(schema_type, list) else ["Unknown"])

        # Build flattened display (mirrors validator.schema.org output)
        flattened = _flatten_value(node)

        # Build validator.schema.org-style display
        # Each field shown as key → value, nested objects expanded inline
        validator_display = {}
        for k, v in node.items():
            validator_display[k] = _flatten_value(v)

        schema_entry = {
            "id":               schema_id,
            "type":             schema_type,
            "context":          context,
            "block_index":      block_index,
            "is_graph_item":    False,       # updated later
            "graph_position":   None,        # updated later
            "fields_present":   [k for k in node.keys() if not k.startswith("@")],
            "all_fields":       list(node.keys()),
            "data":             flattened,          # raw nested (original)
            "validator_display": validator_display, # resolved nested (mirrors validator.schema.org)
            "validation":       [],
            "errors":           0,
            "warnings":         0,
        }

        issues = []

        # 1. Required field checks per type
        for t in types:
            for field_name in REQUIRED_FIELDS.get(t, []):
                # Field is missing entirely
                if field_name not in node:
                    schema_entry["validation"].append({
                        "severity": "warning",
                        "field":    field_name,
                        "issue":    "missing_recommended_field",
                        "message":  f"'{field_name}' is a recommended field for {t}",
                    })
                    issues.append({
                        "block_index": block_index,
                        "schema_type": t,
                        "severity":    "warning",
                        "issue":       "missing_recommended_field",
                        "message":     f"{t} is missing recommended field '{field_name}'",
                    })
                    schema_entry["warnings"] += 1
                else:
                    val = node[field_name]
                    # Present but empty string
                    if isinstance(val, str) and val.strip() == "":
                        schema_entry["validation"].append({
                            "severity": "warning",
                            "field":    field_name,
                            "issue":    "empty_field_value",
                            "message":  f"'{field_name}' is present but has an empty value",
                        })
                        issues.append({
                            "block_index": block_index,
                            "schema_type": t,
                            "severity":    "warning",
                            "issue":       "empty_field_value",
                            "message":     f"{t}.{field_name} is empty",
                        })
                        schema_entry["warnings"] += 1

        # 2. @id reference check — if node has @id refs in values, verify they exist
        for key, val in node.items():
            if isinstance(val, dict) and "@id" in val and len(val) == 1:
                # Pure reference node: {"@id": "https://...#something"}
                ref_id = val["@id"]
                if ref_id not in id_registry:
                    schema_entry["validation"].append({
                        "severity": "warning",
                        "field":    key,
                        "issue":    "unresolved_id_reference",
                        "message":  f"'{key}' references @id '{ref_id}' which was not found in this page's schema graph",
                    })
                    schema_entry["warnings"] += 1

        # 3. datePublished / dateModified format check
        for date_field in ["datePublished", "dateModified"]:
            if date_field in node:
                val = node[date_field]
                if isinstance(val, str):
                    import re as _re
                    iso_pattern = _re.compile(r"^\d{4}-\d{2}-\d{2}")
                    if not iso_pattern.match(val):
                        schema_entry["validation"].append({
                            "severity": "warning",
                            "field":    date_field,
                            "issue":    "invalid_date_format",
                            "message":  f"'{date_field}' value '{val}' may not be ISO 8601 format",
                        })
                        schema_entry["warnings"] += 1

        return schema_entry, issues

    # ── Step 1: Parse all JSON-LD blocks ──────────────────────────────
    json_ld_blocks    = soup.find_all("script", type="application/ld+json")
    parsed_schemas    = []
    schema_val_issues = []
    id_registry       = {}   # @id → schema node (for cross-ref resolution)

    # First pass: collect all @id values across all blocks and @graph items
    for idx, block in enumerate(json_ld_blocks):
        raw = (block.string or "").strip()
        if not raw:
            continue
        try:
            data = _json.loads(raw)
        except Exception:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
        for item in items:
            if isinstance(item, dict) and "@id" in item:
                id_registry[item["@id"]] = item

    # Second pass: parse, validate, flatten
    for idx, block in enumerate(json_ld_blocks):
        raw = (block.string or "").strip()
        if not raw:
            continue

        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as e:
            schema_val_issues.append({
                "block_index": idx,
                "schema_type": "unknown",
                "severity":    "critical",
                "issue":       "invalid_json",
                "message":     f"JSON-LD block {idx+1} has invalid JSON — {str(e)}",
                "raw_snippet": raw[:150],
            })
            parsed_schemas.append({
                "id":           f"block_{idx}_parse_error",
                "type":         "PARSE_ERROR",
                "context":      "",
                "block_index":  idx,
                "fields_present": [],
                "data":         {"raw_snippet": raw[:150]},
                "validation":   [{"severity": "critical", "issue": "invalid_json", "message": str(e)}],
                "errors":       1,
                "warnings":     0,
            })
            continue

        # Root @context for the block (inherited by @graph children)
        block_context = data.get("@context", "https://schema.org") if isinstance(data, dict) else "https://schema.org"

        # Expand @graph or treat root as single item
        items = data.get("@graph", [data]) if isinstance(data, dict) else [data]
        is_graph = "@graph" in (data if isinstance(data, dict) else {})

        for item_idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            # Inherit block @context if item doesn't have its own
            if "@context" not in item:
                item = {"@context": block_context, **item}

            schema_entry, item_issues = _validate_schema_node(item, idx, id_registry)
            schema_entry["is_graph_item"] = is_graph
            schema_entry["graph_position"] = item_idx if is_graph else None

            # Collect types into top-level report
            t = item.get("@type", "Unknown")
            all_types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            for typ in all_types:
                if typ not in report.schema_types:
                    report.schema_types.append(typ)

            parsed_schemas.append(schema_entry)
            schema_val_issues.extend(item_issues)

    # ── Step 2: Microdata (itemscope / itemtype) ──────────────────────
    microdata_items = soup.find_all(attrs={"itemtype": True})
    microdata_types = []
    for el in microdata_items:
        itype = el.get("itemtype", "").strip()
        if itype and itype not in microdata_types:
            microdata_types.append(itype)
    report.microdata_types = microdata_types

    # ── Step 3: RDFa (typeof=) ────────────────────────────────────────
    rdfa_items = soup.find_all(attrs={"typeof": True})
    rdfa_types = []
    for el in rdfa_items:
        rtype = el.get("typeof", "").strip()
        if rtype and rtype not in rdfa_types:
            rdfa_types.append(rtype)
    report.rdfa_types = rdfa_types

    # ── Step 4: Finalize onto report ──────────────────────────────────
    report.has_schema_markup         = len(parsed_schemas) > 0 or len(microdata_types) > 0 or len(rdfa_types) > 0
    report.schema_count              = len(parsed_schemas)
    report.schemas                   = parsed_schemas
    report.schema_validation_issues  = schema_val_issues

    total_errors   = sum(s.get("errors", 0)   for s in parsed_schemas)
    total_warnings = sum(s.get("warnings", 0) for s in parsed_schemas)

    if not report.has_schema_markup:
        add_issue("missing_schema",
                  "No structured data found (JSON-LD, Microdata, or RDFa)",
                  recommendation="Add Schema.org structured data relevant to your page type.")
    else:
        if total_errors > 0:
            add_issue("schema_invalid_json",
                      f"{total_errors} schema block(s) contain invalid JSON",
                      value=str(total_errors),
                      recommendation="Fix JSON syntax errors — use validator.schema.org to test.")
        if total_warnings > 0:
            add_issue("schema_missing_fields",
                      f"{total_warnings} recommended schema fields are missing across {len(parsed_schemas)} schema(s)",
                      value=str(total_warnings),
                      recommendation="Fill in all recommended fields to qualify for Google Rich Results.")

    
        # ── HREFLANG ───────────────────────────────────────────────────────
    hreflang_tags = soup.find_all("link", rel=lambda r: r and "alternate" in r, hreflang=True)
    report.has_hreflang = len(hreflang_tags) > 0

    # ── CONTENT / WORD COUNT ───────────────────────────────────────────
    body = soup.find("body")
    if body:
        text = body.get_text(separator=" ", strip=True)
        words = text.split()
        report.word_count = len(words)
        report.paragraph_count = len(soup.find_all("p"))

    report.has_thin_content = report.word_count < 300
    if report.has_thin_content:
        add_issue("thin_content", f"Only {report.word_count} words on page (min recommended: 300)",
                  value=str(report.word_count),
                  recommendation="Expand page content to at least 300–500 words for better topical relevance.")

    # ── IMAGES ─────────────────────────────────────────────────────────
    images = soup.find_all("img")
    report.total_images = len(images)
    missing_alt_imgs = []
    for img in images:
        alt = img.get("alt")
        if alt is None or alt.strip() == "":
            missing_alt_imgs.append(img.get("src", "unknown"))
    report.images_missing_alt = len(missing_alt_imgs)
    report.images_missing_alt_urls = missing_alt_imgs[:10]  # cap for output size

    if report.images_missing_alt > 0:
        add_issue("images_missing_alt",
                  f"{report.images_missing_alt} of {report.total_images} images are missing alt text",
                  value=str(report.images_missing_alt),
                  recommendation="Add descriptive alt text to all images for accessibility and image SEO.")

    # ── LAZY LOADING ───────────────────────────────────────────────────
    lazy_imgs = [img for img in images if img.get("loading") == "lazy"]
    report.has_lazy_loading = len(lazy_imgs) > 0

    # ── LINKS ──────────────────────────────────────────────────────────
    all_links = soup.find_all("a", href=True)
    internal_links = []
    external_links = []
    generic_anchors = ["click here", "read more", "here", "learn more", "this", "link"]
    generic_anchor_count = 0

    for a in all_links:
        href = a.get("href", "").strip()
        anchor_text = a.get_text(strip=True).lower()

        if anchor_text in generic_anchors:
            generic_anchor_count += 1

        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        abs_href = urljoin(url, href)
        link_domain = urlparse(abs_href).netloc

        if link_domain == base_domain or link_domain == "":
            internal_links.append(abs_href)
        else:
            external_links.append(abs_href)

    report.internal_links = len(internal_links)
    report.external_links = len(external_links)
    report.internal_link_urls = list(set(internal_links))[:50]  # cap for output

    report.generic_anchor_count = generic_anchor_count
    if generic_anchor_count > 3:
        add_issue("generic_anchors", f"{generic_anchor_count} links use generic anchor text",
                  value=str(generic_anchor_count),
                  recommendation="Replace generic anchors like 'click here' with descriptive keyword-rich text.")

    # ── RENDER BLOCKING SCRIPTS ────────────────────────────────────────
    head = soup.find("head")
    blocking_scripts = 0
    if head:
        for script in head.find_all("script", src=True):
            if not script.get("async") and not script.get("defer"):
                blocking_scripts += 1
    report.render_blocking_scripts = blocking_scripts
    if blocking_scripts > 0:
        add_issue("render_blocking_scripts",
                  f"{blocking_scripts} render-blocking <script> tags in <head>",
                  value=str(blocking_scripts),
                  recommendation="Add 'async' or 'defer' to script tags, or move them before </body>.")

    # ── MIXED CONTENT ──────────────────────────────────────────────────
    if report.is_https:
        mixed = soup.find_all(src=re.compile(r"^http://"))
        report.mixed_content_count = len(mixed)
        if report.mixed_content_count > 0:
            add_issue("mixed_content",
                      f"{report.mixed_content_count} resources loaded over HTTP on an HTTPS page",
                      value=str(report.mixed_content_count),
                      recommendation="Update all resource URLs to use HTTPS.")

    # ── RESPONSE HEADERS ───────────────────────────────────────────────
    headers_lower = {k.lower(): v for k, v in response_headers.items()}

    report.has_gzip = "gzip" in headers_lower.get("content-encoding", "").lower()
    report.has_cache_headers = bool(
        headers_lower.get("cache-control") or headers_lower.get("expires")
    )
    if not report.has_cache_headers:
        add_issue("missing_cache_headers", "No Cache-Control or Expires headers found",
                  recommendation="Set Cache-Control headers to improve repeat visit performance.")

    # Security headers check
    security_checks = {
        "x-frame-options":          "Prevents clickjacking attacks",
        "x-content-type-options":   "Prevents MIME sniffing",
        "strict-transport-security":"Enforces HTTPS (HSTS)",
        "content-security-policy":  "Controls resource loading (CSP)",
        "referrer-policy":          "Controls referrer information",
    }
    missing_sec = []
    for h, desc in security_checks.items():
        present = h in headers_lower
        report.security_headers[h] = {"present": present, "description": desc}
        if not present:
            missing_sec.append(h)

    if len(missing_sec) >= 3:
        add_issue("missing_security_headers",
                  f"{len(missing_sec)} important security headers are missing",
                  value=", ".join(missing_sec),
                  recommendation="Configure your web server to send security headers like HSTS, CSP, X-Frame-Options.")

    # ── FINALIZE ───────────────────────────────────────────────────────
    report.issues = [asdict(i) for i in issues]
    return report    # ── SCHEMA MARKUP (deep extraction + validation) ──────────────────
    import json as _json

    # ── Required fields per schema type (for validation) ──────────
    REQUIRED_FIELDS = {
        "Organization":        ["name", "url"],
        "LocalBusiness":       ["name", "address", "telephone"],
        "WebSite":             ["name", "url"],
        "WebPage":             ["name", "url"],
        "Article":             ["headline", "author", "datePublished", "image"],
        "BlogPosting":         ["headline", "author", "datePublished", "image"],
        "NewsArticle":         ["headline", "author", "datePublished", "image"],
        "Product":             ["name", "image", "description", "offers"],
        "Review":              ["reviewRating", "author", "itemReviewed"],
        "FAQPage":             ["mainEntity"],
        "HowTo":               ["name", "step"],
        "BreadcrumbList":      ["itemListElement"],
        "Person":              ["name"],
        "Event":               ["name", "startDate", "location"],
        "JobPosting":          ["title", "description", "datePosted", "hiringOrganization"],
        "Recipe":              ["name", "recipeIngredient", "recipeInstructions"],
        "VideoObject":         ["name", "description", "thumbnailUrl", "uploadDate"],
        "Course":              ["name", "description", "provider"],
        "SoftwareApplication": ["name", "operatingSystem", "applicationCategory"],
        "Service":             ["name", "provider"],
        "ImageObject":         ["url", "contentUrl"],
        "SearchAction":        ["target", "query-input"],
        "ListItem":            ["position", "name"],
        "ReadAction":          ["target"],
    }

    def _flatten_value(val, depth=0):
        """
        Recursively flatten a schema value into a human-readable form.
        Handles: strings, numbers, bools, dicts (nested schemas), lists.
        Mirrors exactly how validator.schema.org displays nested objects.
        """
        if depth > 6:
            return val  # prevent infinite recursion on circular refs

        if val is None:
            return None
        if isinstance(val, (str, int, float, bool)):
            return val
        if isinstance(val, list):
            if len(val) == 1:
                return _flatten_value(val[0], depth + 1)
            return [_flatten_value(v, depth + 1) for v in val]
        if isinstance(val, dict):
            return _parse_schema_node(val, depth + 1)
        return val

    def _parse_schema_node(node: dict, depth=0) -> dict:
        """
        Parse a single schema node recursively.
        Returns a structured dict with:
          - @type, @id, @context at top level
          - all other fields with their values recursively flattened
          - validation errors for this node
        """
        if not isinstance(node, dict):
            return node

        schema_type = node.get("@type", "Unknown")
        types = [schema_type] if isinstance(schema_type, str) else (schema_type or ["Unknown"])

        parsed = {
            "@type":   schema_type,
            "@id":     node.get("@id", ""),
            "fields":  {},
            "validation": [],
        }

        # Parse every field in the node
        for key, val in node.items():
            if key in ("@type", "@id", "@context", "@graph"):
                continue
            parsed["fields"][key] = _flatten_value(val, depth)

        # Validation: check required fields per type
        for t in types:
            required = REQUIRED_FIELDS.get(t, [])
            for req_field in required:
                if req_field not in node:
                    parsed["validation"].append({
                        "severity": "warning",
                        "issue":    "missing_recommended_field",
                        "field":    req_field,
                        "message":  f"'{t}' is missing recommended field: '{req_field}'",
                    })

        # Validation: empty string values in important fields
        for f in ["name", "url", "description", "headline", "image", "contentUrl"]:
            v = node.get(f)
            if isinstance(v, str) and v.strip() == "":
                parsed["validation"].append({
                    "severity": "warning",
                    "issue":    "empty_field_value",
                    "field":    f,
                    "message":  f"Field '{f}' is present but empty",
                })

        return parsed

    # ── Main extraction loop ───────────────────────────────────────
    json_ld_blocks = soup.find_all("script", type="application/ld+json")
    parsed_schemas     = []   # final list of parsed schema entries
    schema_val_issues  = []   # rolled-up validation issues

    for block_idx, block in enumerate(json_ld_blocks):
        raw = (block.string or "").strip()
        if not raw:
            continue

        # Parse JSON
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError as e:
            schema_val_issues.append({
                "block_index":  block_idx,
                "severity":     "critical",
                "issue":        "invalid_json",
                "message":      f"JSON-LD block {block_idx+1} has invalid JSON: {str(e)}",
                "raw_snippet":  raw[:200],
            })
            continue

        top_context = data.get("@context", "https://schema.org") if isinstance(data, dict) else "https://schema.org"

        # ── Handle @graph (Yoast / Rank Math style) ────────────────
        # @graph = array of linked schema nodes in one block
        if isinstance(data, dict) and "@graph" in data:
            graph_items = data["@graph"]
            if not isinstance(graph_items, list):
                graph_items = [graph_items]

            # Build @id lookup map for cross-reference resolution
            id_map = {}
            for item in graph_items:
                if isinstance(item, dict) and item.get("@id"):
                    id_map[item["@id"]] = item

            for item in graph_items:
                if not isinstance(item, dict):
                    continue
                _extract_schema_item(
                    item, block_idx, top_context,
                    parsed_schemas, schema_val_issues,
                    report, _parse_schema_node, id_map
                )

        # ── Single schema or array of schemas ─────────────────────
        else:
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                _extract_schema_item(
                    item, block_idx, top_context,
                    parsed_schemas, schema_val_issues,
                    report, _parse_schema_node, {}
                )

    # ── Microdata (itemscope / itemtype) ───────────────────────────
    microdata_items = soup.find_all(attrs={"itemtype": True})
    microdata_types = []
    for el in microdata_items:
        itype = el.get("itemtype", "").strip()
        if itype and itype not in microdata_types:
            microdata_types.append(itype)
    report.microdata_types = microdata_types

    # ── RDFa (typeof=) ────────────────────────────────────────────
    rdfa_items = soup.find_all(attrs={"typeof": True})
    rdfa_types = []
    for el in rdfa_items:
        rtype = el.get("typeof", "").strip()
        if rtype and rtype not in rdfa_types:
            rdfa_types.append(rtype)
    report.rdfa_types = rdfa_types

    # ── Finalize ──────────────────────────────────────────────────
    report.has_schema_markup         = len(parsed_schemas) > 0 or bool(microdata_types) or bool(rdfa_types)
    report.schema_count              = len(parsed_schemas)
    report.schemas                   = parsed_schemas
    report.schema_validation_issues  = schema_val_issues

    if not report.has_schema_markup:
        add_issue("missing_schema",
                  "No structured data found (JSON-LD, Microdata, or RDFa)",
                  recommendation="Add Schema.org JSON-LD structured data (Organization, WebPage, Article, etc.)")
    else:
        critical_val = [i for i in schema_val_issues if i["severity"] == "critical"]
        warning_val  = [i for i in schema_val_issues if i["severity"] == "warning"]
        if critical_val:
            add_issue("schema_invalid_json",
                      f"{len(critical_val)} JSON-LD block(s) contain invalid JSON",
                      value=str(len(critical_val)),
                      recommendation="Fix JSON syntax errors in your structured data.")
        if warning_val:
            add_issue("schema_missing_fields",
                      f"{len(warning_val)} recommended schema fields are missing",
                      value="; ".join(set(i.get("message","") for i in warning_val[:3])),
                      recommendation="Fill in all recommended fields to qualify for Google Rich Results.")
