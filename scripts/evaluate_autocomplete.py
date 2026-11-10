#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "dronefly-core"
# ]
# ///
import sys
from dataclasses import dataclass
import time
from dronefly.core import Context, iNatClient
from dronefly.miner import taxon_autocomplete

from pyinaturalist_convert.fts import BaseSearchStrategy, TaxonAdvancedSearchStrategy, TaxonSimpleSearchStrategy

@dataclass
class EvalCase:
    name: str
    text: str
    taxon_id: int | None = None
    language: str | None = None
    rank: str | None = None
    limit: int = 200

# Define your test suite here
TEST_SUITES = [
    EvalCase(
        name="Halictidae + 'gold'",
        text="gold",
        taxon_id=49707,
    ),
    EvalCase(
        name="Global + 'butter'",
        text="butter",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'butter and'",
        text="butter and",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'butter and eggs'",
        text="butter and eggs",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'extra extra'",
        text="extra extra",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'sarco'",
        text="sarco",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'squirrel'",
        text="squirrel",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'pseudoscorp'",
        text="pseudoscorp",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'scoter'",
        text="scoter",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'mold'",
        text="mold",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'lunula'",
        text="lunula",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'spinach'",
        text="spinach",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'goose'",
        text="goose",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'skunk'",
        text="skunk",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'roadrunner'",
        text="roadrunner",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'copperhead'",
        text="copperhead",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'creosote'",
        text="creosote",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'longspur'",
        text="longspur",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'hoggi'",
        text="hoggi",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'trump'",
        text="trump",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'san'",
        text="san",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'rhodo arbores'",
        text="rhodo arbores",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'macrosoma leuc'",
        text="macrosoma leuc",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'tylos punct'",
        text="tylos punct",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'o dentex'",
        text="o dentex",
        taxon_id=None,
    ),
    EvalCase(
        name="Global + 'mer trans'",
        text="mer trans",
        taxon_id=None,
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
            ttl=14400, # 4 hour ttl to make test results stable across many consecutive iterations
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
        
        agreement = (2.0 * intersect_len) / (len(set_l) + len(set_a)) if (len(set_l) + len(set_a)) > 0 else 0.0
        score += weight * (p ** (d - 1)) * agreement
        
    return score

def calculate_position_weighted_score(local_items: list[dict], api_items: list[dict], max_k: int = 5) -> float:
    api_id_to_rank = {item["id"]: idx for idx, item in enumerate(api_items[:max_k])}
    total_possible_score = sum(1.0 - (i / max_k) for i in range(max_k))
    earned_score = 0.0
    
    for local_idx, item in enumerate(local_items[:max_k]):
        item_id = item["id"]
        if item_id in api_id_to_rank:
            api_idx = api_id_to_rank[item_id]
            position_diff = abs(local_idx - api_idx)
            slot_weight = 1.0 - (local_idx / max_k)
            distance_penalty = position_diff * 0.15
            earned_score += max(0.0, slot_weight - distance_penalty)
            
    return min(1.0, earned_score / total_possible_score if total_possible_score > 0 else 0.0)

def calculate_overlap_metrics(local_items: list, api_items: list, k: int = 5) -> dict:
    local_ids = {item["id"] for item in local_items[:k]}
    api_ids = {item["id"] for item in api_items[:k]}
    
    intersection = local_ids.intersection(api_ids)
    overlap_ratio = len(intersection) / k if k > 0 else 0.0
    return {
        f"top_{k}_overlap_count": len(intersection),
        f"top_{k}_overlap_pct": overlap_ratio * 100
    }

def run_evaluation(strategy: BaseSearchStrategy | None = None, name: str = None):
    print("==================================================")
    print(f"DETAILED EVALUATION: {name or str(strategy.__class__)}")
    print("==================================================")

    for case in TEST_SUITES:
        print(f"\n[Test Case]: {case.name} (Query: '{case.text}')")
        print("-" * 50)

        start_time = time.perf_counter()
        
        # Safely pass strategy if supported, otherwise omit it for older versions
        kwargs = {
            "text": case.text,
            "taxon_id": case.taxon_id,
            "language": case.language,
            "rank": case.rank,
        }
        try:
            local_raw = taxon_autocomplete(**kwargs, strategy=strategy)
        except TypeError:
            local_raw = taxon_autocomplete(**kwargs)
        if not local_raw:
            # skip this test as nothing was returned
            continue

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Danger zone flag
        status_tag = ""
        if elapsed_ms > 150:
            status_tag = " ⚠️ [DANGER ZONE > 150ms]"
        elif elapsed_ms > 50:
            status_tag = " ⚡ [Yellow Zone > 50ms]"

        print(f"Query '{case.text}' took {elapsed_ms:.2f} ms{status_tag}")

        local_results = [
            {
                "id": t.id,
                "name": t.name,
                "matched_term": getattr(t, "matched_term", ""),
                "observations_count": getattr(t, "observations_count", 0),
            }
            for t in local_raw[:case.limit]
        ]

        api_results = get_api_results(case)

        metrics_5 = calculate_overlap_metrics(local_results, api_results, k=5)
        metrics_10 = calculate_overlap_metrics(local_results, api_results, k=10)
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

STRATEGIES_TO_TEST = {
    "Baseline (Default)": TaxonSimpleSearchStrategy(),
    "Advanced": TaxonAdvancedSearchStrategy(),
    "Strong Sci Phrase Boost": TaxonAdvancedSearchStrategy(sci_phrase_match_boost=-350),
    "Weak Sci Phrase Boost": TaxonAdvancedSearchStrategy(sci_phrase_match_boost=-250),
}

def run_evaluation_suite():
    strategy_scores = {name: {"rbo_sum": 0.0, "pos_sum": 0.0, "case_metrics": {}, "count": 0} for name in STRATEGIES_TO_TEST}
    
    print("Fetching reference results from iNaturalist API...")
    case_api_results = {}
    for case in TEST_SUITES:
        case_api_results[case.name] = get_api_results(case)

    print("Running evaluation suite across all strategies...")
    for case in TEST_SUITES:
        api_results = case_api_results[case.name]

        for strat_name, strategy in STRATEGIES_TO_TEST.items():
            kwargs = {
                "text": case.text,
                "taxon_id": case.taxon_id,
                "language": case.language,
                "rank": case.rank,
            }
            try:
                local_raw = taxon_autocomplete(**kwargs, strategy=strategy)
            except TypeError:
                local_raw = taxon_autocomplete(**kwargs)
            if not local_raw:
                continue

            local_results = [
                {
                    "id": t.id,
                    "name": t.name,
                    "matched_term": getattr(t, "matched_term", ""),
                }
                for t in local_raw[:case.limit]
            ]

            rbo_score = calculate_rbo(local_results, api_results, p=0.85)
            pos_score = calculate_position_weighted_score(local_results, api_results, max_k=5)

            strategy_scores[strat_name]["rbo_sum"] += rbo_score
            strategy_scores[strat_name]["pos_sum"] += pos_score
            strategy_scores[strat_name]["case_metrics"][case.name] = {
                "rbo": rbo_score,
                "pos": pos_score * 100
            }
            strategy_scores[strat_name]["count"] += 1

    strategy_averages = {}
    for strat_name, data in strategy_scores.items():
        avg_rbo = data["rbo_sum"] / data["count"] if data["count"] > 0 else 0.0
        avg_pos = data["pos_sum"] / data["count"] if data["count"] > 0 else 0.0
        strategy_averages[strat_name] = {"avg_rbo": avg_rbo, "avg_pos": avg_pos}

    baseline_rbo = strategy_averages["Baseline (Default)"]["avg_rbo"]
    baseline_pos = strategy_averages["Baseline (Default)"]["avg_pos"]

    print("\n" + "=" * 85)
    print("EVALUATION SUMMARY TABLE (AVERAGES)")
    print("=" * 85)
    print(f"| {'Strategy':<44} | {'Avg RBO Score':<15} | {'Avg Top-5 Pos %':<17} | {'Status':<16} |")
    print("|" + "-" * 46 + "|" + "-" * 17 + "|" + "-" * 19 + "|" + "-" * 18 + "|")

    for strat_name, avgs in strategy_averages.items():
        if strat_name == "Baseline (Default)":
            status = "Baseline"
        elif avgs["avg_rbo"] > baseline_rbo and avgs["avg_pos"] > baseline_pos:
            status = "Improved"
        else:
            status = "No Improvement"

        print(
            f"| {strat_name:<44} | "
            f"{avgs['avg_rbo']:<15.4f} | "
            f"{avgs['avg_pos']:<16.2f}% | "
            f"{status:<16} |"
        )
    print("=" * 85)

    print("\n" + "=" * 50)
    print("STRATEGY DETAILED EVALUATION RESULTS")
    print("=" * 50)

    for strat_name, strategy in STRATEGIES_TO_TEST.items():
        if strat_name == "Baseline (Default)":
            continue
        
        avgs = strategy_averages[strat_name]
        if avgs["avg_rbo"] >= baseline_rbo or avgs["avg_pos"] >= baseline_pos:
            print(f"\n-> Strategy '{strat_name}' showed positive/equal movement. Displaying details:")
            run_evaluation(strategy=strategy, name=strat_name)
        else:
            print(f"\n-> Strategy '{strat_name}' failed to make an improvement (Avg RBO: {avgs['avg_rbo']:.4f} vs Baseline: {baseline_rbo:.4f}).")

    # --- TOP STRATEGIES SUMMARY ---
    print("\n" + "=" * 115)
    print("TOP STRATEGIES VS. CURRENT BASELINE SUMMARY")
    print("=" * 115)
    
    sorted_candidates = sorted(
        [s for s in STRATEGIES_TO_TEST.keys() if s != "Baseline (Default)"],
        key=lambda s: (strategy_averages[s]["avg_rbo"] + strategy_averages[s]["avg_pos"]/100),
        reverse=True
    )

    print(f"| {'Strategy':<44} | {'Avg RBO (vs Base)':<20} | {'Avg Top-5 Pos % (vs Base)':<25} | {'Category Result':<18} |")
    print("|" + "-" * 46 + "|" + "-" * 22 + "|" + "-" * 27 + "|" + "-" * 20 + "|")

    for strat_name in sorted_candidates:
        avgs = strategy_averages[strat_name]
        rbo_diff = avgs["avg_rbo"] - baseline_rbo
        pos_diff = avgs["avg_pos"] - baseline_pos
        
        rbo_str = f"{avgs['avg_rbo']:.4f} ({'+' if rbo_diff >= 0 else ''}{rbo_diff:.4f})"
        pos_str = f"{avgs['avg_pos']:.2f}% ({'+' if pos_diff >= 0 else ''}{pos_diff:.2f}%)"
        
        status = "Improved" if (avgs["avg_rbo"] >= baseline_rbo and avgs["avg_pos"] >= baseline_pos) else ("Mixed" if (avgs["avg_rbo"] > baseline_rbo or avgs["avg_pos"] > baseline_pos) else "No Improvement")

        print(
            f"| {strat_name:<44} | "
            f"{rbo_str:<20} | "
            f"{pos_str:<25} | "
            f"{status:<18} |"
        )
    print("=" * 115)

if __name__ == "__main__":
    run_evaluation_suite()
