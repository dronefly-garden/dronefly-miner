import sys
from dataclasses import dataclass
from typing import Any
from pprint import pprint
from dronefly.core import Context, iNatClient
from dronefly.miner import taxon_autocomplete
from pyinaturalist_convert.fts import TaxonScoringStrategy

@dataclass
class EvalCase:
    name: str
    text: str
    taxon_id: int | None = None
    language: str | None = None
    rank: str | None = None
    limit: int = 10

# Define your test suite here
TEST_SUITES = [
    EvalCase(
        name="Halictidae + 'gold'",
        text="gold",
        taxon_id=49707,
        limit=10
    ),
    EvalCase(
        name="Global + 'butter'",
        text="butter",
        taxon_id=None,
        limit=10
    ),
    EvalCase(
        name="Global + 'butter and'",
        text="butter and",
        taxon_id=None,
        limit=10
    ),
    EvalCase(
        name="Global + 'butter and eggs'",
        text="butter and eggs",
        taxon_id=None,
        limit=10
    ),
]

def get_api_results(case: EvalCase) -> list[dict]:
    """Fetches results from the live iNat API for comparison."""
    client = iNatClient()
    client.ctx = Context()
    try:
        response = client.taxa.autocomplete(
            q=case.text,
            taxon_id=case.taxon_id,
            per_page=case.limit,
            all_names=True,
            limit=case.limit,
        )
        items = response.all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "matched_term": getattr(t, "matched_term", getattr(t, "matched_common_name", "")),
                "observations_count": getattr(t, "observations_count", 0),
            }
            for t in items[:case.limit]
        ]
    except Exception as e:
        print(f"API Error for '{case.text}': {e}", file=sys.stderr)
        return []

def calculate_rbo(local_items: list[dict], api_items: list[dict], p: float = 0.85) -> float:
    """
    Calculates Rank-Biased Overlap (RBO) between two ranked lists.
    p (0 < p < 1) controls persistence: higher values give more weight to deeper items,
    lower values focus heavily on the top few results (e.g., p=0.85 weights the top ~5 heavily).
    """
    local_ids = [item["id"] for item in local_items]
    api_ids = [item["id"] for item in api_items]
    
    k = max(len(local_ids), len(api_ids))
    if k == 0:
        return 1.0

    score = 0.0
    weight = 1.0 - p
    
    for d in range(1, k + 1):
        set_l = set(local_ids[:d])
        set_a = set(api_ids[:d])
        intersect_len = len(set_l.intersection(set_a))
        
        # Agreement at depth d
        agreement = (2.0 * intersect_len) / (len(set_l) + len(set_a)) if (len(set_l) + len(set_a)) > 0 else 0.0
        score += weight * (p ** (d - 1)) * agreement
        
    return score

def calculate_position_weighted_score(local_items: list[dict], api_items: list[dict], max_k: int = 5) -> float:
    """
    Computes a score from 0.0 to 1.0 based on position alignment.
    An item matching at rank 1 gives full weight; lower ranks decay linearly.
    """
    api_id_to_rank = {item["id"]: idx for idx, item in enumerate(api_items[:max_k])}
    
    total_possible_score = sum(1.0 - (i / max_k) for i in range(max_k))
    earned_score = 0.0
    
    for local_idx, item in enumerate(local_items[:max_k]):
        item_id = item["id"]
        if item_id in api_id_to_rank:
            api_idx = api_id_to_rank[item_id]
            # Reward proximity: small position difference gets higher points
            position_diff = abs(local_idx - api_idx)
            # Base weight for the slot minus a penalty for distance
            slot_weight = 1.0 - (local_idx / max_k)
            distance_penalty = position_diff * 0.15
            earned_score += max(0.0, slot_weight - distance_penalty)
            
    return min(1.0, earned_score / total_possible_score if total_possible_score > 0 else 0.0)

def calculate_overlap_metrics(local_items: list, api_items: list, k: int = 5) -> dict:
    """Calculates top-K set intersection overlap."""
    local_ids = {item["id"] for item in local_items[:k]}
    api_ids = {item["id"] for item in api_items[:k]}
    
    intersection = local_ids.intersection(api_ids)
    overlap_ratio = len(intersection) / k if k > 0 else 0.0
    return {
        f"top_{k}_overlap_count": len(intersection),
        f"top_{k}_overlap_pct": overlap_ratio * 100
    }

def run_evaluation(strategy: TaxonScoringStrategy | None = None):
    print("==================================================")
    print("RUNNING AUTOCOMPLETE RANKING EVALUATION")
    print("==================================================")

    for case in TEST_SUITES:
        print(f"\n[Test Case]: {case.name} (Query: '{case.text}')")
        print("-" * 50)

        # 1. Fetch Local Results
        local_raw = taxon_autocomplete(
            text=case.text,
            taxon_id=case.taxon_id,
            language=case.language,
            rank=case.rank,
            strategy=strategy
        )[:case.limit]
        
        local_results = [
            {
                "id": t.id,
                "name": t.name,
                "matched_term": getattr(t, "matched_term", ""),
                "observations_count": getattr(t, "observations_count", 0), # if exposed on Taxon
            }
            for t in local_raw
        ]

        # 2. Fetch API Results
        api_results = get_api_results(case)

        # 3. Compute Metrics
        metrics_5 = calculate_overlap_metrics(local_results, api_results, k=5)
        metrics_10 = calculate_overlap_metrics(local_results, api_results, k=10)
        # Compute position-aware metrics (focusing on top 5 where autocomplete matters most)
        rbo_score = calculate_rbo(local_results, api_results, p=0.85)
        pos_score = calculate_position_weighted_score(local_results, api_results, max_k=5)

        print(f"Metrics -> RBO Score: {rbo_score:.2f} | Position-Weighted Match (Top-5): {pos_score * 100:.1f}%")
        print(f"Metrics -> Top-5 Overlap: {metrics_5['top_5_overlap_pct']}% | Top-10 Overlap: {metrics_10['top_10_overlap_pct']}%")
        print("\nPosition | Local Result (Name / Obs)                  | API Result (Name / Obs)")
        print("-" * 80)

        max_len = max(len(local_results), len(api_results))
        for i in range(max_len):
            loc_str = "---"
            if i < len(local_results):
                r = local_results[i]
                loc_str = f"{r['name']} ({r['observations_count']} obs)"
            
            api_str = "---"
            if i < len(api_results):
                r = api_results[i]
                api_str = f"{r['name']} ({r['observations_count']} obs)"

            print(f"   {i+1:2d}    | {loc_str:<42} | {api_str}")
        print("\n" + "=" * 50)

if __name__ == "__main__":
    # You can pass custom strategies here to test variations!
    run_evaluation()
    