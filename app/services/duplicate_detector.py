"""
Deterministic duplicate detection.

Priority:
1. exact_match: email (normalized lowercase) or phone (normalized digits)
2. possible_duplicate: normalized name + company name exact match or similarity > threshold

The LLM must NEVER be allowed to merge; human review required.
"""
import re
from typing import Optional, Tuple
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.models.database import Contact

def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.strip().lower()

def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    # keep only digits and leading +
    digits = re.sub(r"[^\d+]", "", phone)
    # remove leading zeros/spaces etc; keep as digits
    digits = re.sub(r"\D", "", digits)
    return digits if digits else None

def normalize_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.strip().lower()
    n = re.sub(r"\s+", " ", n)
    return n

def normalize_company(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = name.strip().lower()
    # remove common suffixes for better matching
    suffixes = [" inc", " llc", " ltd", " co", " corp", " gmbh", " pty", ".com", " inc.", " ltd."]
    for s in suffixes:
        if n.endswith(s):
            n = n[: -len(s)]
    n = re.sub(r"\s+", " ", n).strip()
    # remove punctuation
    n = re.sub(r"[^a-z0-9 ]", "", n)
    return n.strip() or None

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def find_duplicate(
    db: Session,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    company: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Contact]]:
    """
    Returns (duplicate_status, matched_contact)
    duplicate_status: "exact_match" | "possible_duplicate" | None
    """
    norm_email = normalize_email(email)
    norm_phone = normalize_phone(phone)

    # 1. Exact match on email
    if norm_email:
        contact = db.query(Contact).filter(Contact.normalized_email == norm_email).first()
        if contact:
            return "exact_match", contact

    # Exact match on phone (if provided and normalized length reasonable)
    if norm_phone and len(norm_phone) >= 7:
        contact = db.query(Contact).filter(Contact.normalized_phone == norm_phone).first()
        if contact:
            return "exact_match", contact

    # 2. Possible duplicate: name + company
    norm_name = normalize_name(name)
    norm_company = normalize_company(company)

    if norm_name or norm_company:
        # Fetch candidates with at least one of name/company non-null
        candidates = db.query(Contact).all()
        for c in candidates:
            # Compare normalized company exact
            if norm_company and c.normalized_name and c.company and c.company.normalized_name:
                # both have company: check company exact + name similarity
                if norm_company == c.company.normalized_name:
                    # name similarity check
                    if norm_name and c.normalized_name:
                        if norm_name == c.normalized_name or similarity(norm_name, c.normalized_name) > 0.85:
                            return "possible_duplicate", c
                        # even if name not perfect but company exact + name partial?
                        # require name token overlap
                        if len(norm_name.split()) and len(c.normalized_name.split()):
                            # if first name or last name matches
                            if norm_name.split()[0] == c.normalized_name.split()[0]:
                                return "possible_duplicate", c
                    else:
                        # no name provided but company exact => possible
                        return "possible_duplicate", c
            # No company but name exact
            if norm_name and c.normalized_name and norm_name == c.normalized_name:
                # name exact alone considered possible duplicate (conservative)
                return "possible_duplicate", c
            # Similarity fallback: both name and company high similarity
            if norm_name and c.normalized_name and norm_company and c.company and c.company.normalized_name:
                name_sim = similarity(norm_name, c.normalized_name)
                comp_sim = similarity(norm_company, c.company.normalized_name)
                if name_sim > 0.85 and comp_sim > 0.85:
                    return "possible_duplicate", c

    return None, None
