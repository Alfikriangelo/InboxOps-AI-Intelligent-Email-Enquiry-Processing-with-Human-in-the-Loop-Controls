"""
Routing Service — Option B (scalable, no manual keyword lists).

LLM generates intent_keywords + intent; deterministic code maps them to a real-world team
via TF-IDF cosine similarity against TEAM_DESCRIPTIONS (config). Add a team = add description,
no code change. LLM 100% determines keywords, deterministic determines routing.

Real-world teams: sales, support, billing_finance, partnership, operations, marketing, hr, legal, triage
"""
import re
import math
from typing import Dict, List, Tuple, Optional

from app.core.config import settings
from app.models.schemas import ClassificationEnum, TeamEnum

# Minimal stopwords for tokenization
_STOPWORDS = {
    "the", "and", "for", "with", "are", "our", "you", "your", "have", "has", "this", "that",
    "from", "about", "please", "thanks", "thank", "hello", "hi", "dear", "we", "i", "am", "is",
    "a", "an", "to", "of", "in", "on", "at", "be", "by", "as", "it", "or", "was", "were",
    "will", "would", "could", "should", "can", "need", "needs", "want", "looking", "interested",
}

def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    toks = re.findall(r"[a-z]{3,}", text.lower())
    return [t for t in toks if t not in _STOPWORDS]

def _tf(tokens: List[str]) -> Dict[str, float]:
    if not tokens:
        return {}
    n = len(tokens)
    cnt: Dict[str, int] = {}
    for t in tokens:
        cnt[t] = cnt.get(t, 0) + 1
    return {k: v / n for k, v in cnt.items()}

def _idf(corpus_tokens: List[List[str]]) -> Dict[str, float]:
    N = len(corpus_tokens)
    df: Dict[str, int] = {}
    for toks in corpus_tokens:
        seen = set(toks)
        for t in seen:
            df[t] = df.get(t, 0) + 1
    idf = {}
    for tok, d in df.items():
        idf[tok] = math.log((N + 1) / (d + 1)) + 1  # smoothed
    return idf

def _tfidf_vec(tokens: List[str], idf: Dict[str, float]) -> Dict[str, float]:
    tf = _tf(tokens)
    return {tok: tf_val * idf.get(tok, 1.0) for tok, tf_val in tf.items()}

def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # dot
    common = set(a.keys()) & set(b.keys())
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def _team_descriptions() -> Dict[str, str]:
    return settings.TEAM_DESCRIPTIONS

# Opsi A: source as embedding feature — not manual if, but context for TF-IDF
_SOURCE_CONTEXT: Dict[str, str] = {
    "email": "email formal business proposal professional correspondence",
    "website": "website form lead marketing sales inbound contact form",
    "messaging": "messaging chat whatsapp telegram urgent short instant support help",
}

def _augment_query_with_source(query: str, source: Optional[str]) -> str:
    if not source:
        return query
    ctx = _SOURCE_CONTEXT.get(source.lower(), "")
    if ctx:
        return f"{query} {ctx}"
    return query

def score_teams(query: str, source: Optional[str] = None) -> List[Tuple[TeamEnum, float]]:
    """Return teams scored by similarity to query. Sorted descending. Source augments query (Opsi A)."""
    if source:
        query = _augment_query_with_source(query, source)
    team_descs = _team_descriptions()
    team_names = list(team_descs.keys())
    corpus_tokens = [_tokenize(desc) for desc in team_descs.values()]
    query_tokens = _tokenize(query)
    # Build idf over corpus + query for better discrimination
    all_tokens = corpus_tokens + [query_tokens]
    idf = _idf(all_tokens)
    query_vec = _tfidf_vec(query_tokens, idf)
    scores: List[Tuple[TeamEnum, float]] = []
    for name in team_names:
        desc_tokens = _tokenize(team_descs[name])
        vec = _tfidf_vec(desc_tokens, idf)
        sim = _cosine(query_vec, vec)
        try:
            team_enum = TeamEnum(name)
        except ValueError:
            continue
        scores.append((team_enum, sim))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores

def route_team(query: str, classification: Optional[ClassificationEnum] = None, source: Optional[str] = None) -> TeamEnum:
    """
    Deterministically route to a real-world team via embedding similarity (Option B + Opsi A source).
    - LLM supplies keywords/intent; we embed them + source context vs team descriptions.
    - Junk/insufficient always -> triage (no manual keyword check).
    - Below threshold -> triage.
    """
    # Direct fallback for junk/insufficient
    if classification is not None:
        cls_val = classification.value if hasattr(classification, "value") else str(classification)
        if cls_val in ("junk", "insufficient_information"):
            return TeamEnum.triage

    scores = score_teams(query, source=source)
    if not scores:
        return TeamEnum.triage
    best_team, best_score = scores[0]
    threshold = getattr(settings, "ROUTING_SIMILARITY_THRESHOLD", 0.12)
    if best_score < threshold:
        return TeamEnum.triage
    return best_team

def get_team_owner(team: TeamEnum) -> str:
    owners = getattr(settings, "TEAM_OWNERS", {})
    key = team.value if hasattr(team, "value") else str(team)
    return owners.get(key, owners.get("triage", "owner_triage@beda.id"))

def explain_routing(query: str, source: Optional[str] = None) -> Dict[str, float]:
    return {team.value: round(score, 4) for team, score in score_teams(query, source=source)}
