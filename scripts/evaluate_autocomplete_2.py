#!/usr/bin/env python3
import re
import subprocess
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse, unquote
import sqlite3

from pyinaturalist_convert import TaxonAutocompleter
from dronefly.miner import taxon_autocomplete, DB_PATH

autocompleter = TaxonAutocompleter(db_path=DB_PATH, limit=200)

# Regex to detect less interesting queries that may not reliably
# match any desired taxon
# - hybrid markers like ' x ' or ' × ' as a separate token
# - too short (1 or 2 characters)
RE_DISCARD = re.compile(r'(\b[x×]\b|^.{1,2}$)')

OUTPUT_CSV = "ground_truth_eval.csv"

# Regex to capture the full querystring after autocomplete?
# Example: GET https://api.inaturalist.org/v1/taxa/autocomplete?q=common+bluetongue&...
RE_AUTOCOMPLETE = re.compile(
    r'(?P<timestamp>[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}).*?GET\s+https://api\.inaturalist\.org/v1/taxa/autocomplete\?(?P<querystring>[^\s]+)'
)

# Example: GET https://api.inaturalist.org/v1/taxa/37456?preferred_place_id=...
RE_TAXON_DETAIL = re.compile(
    r'(?P<timestamp>[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}).*?GET\s+https://api\.inaturalist\.org/v1/taxa/(?P<taxon_id>\d+)\?'
)

def parse_log_timestamp(ts_str):
    """Parse journalctl timestamp string (assumes current year)."""
    current_year = datetime.now().year
    dt = datetime.strptime(f"{current_year} {ts_str}", "%Y %b %d %H:%M:%S")
    return dt

def get_autocomplete_results(query_lower, taxon_id):
    results = taxon_autocomplete(text=query_lower, autocompleter=autocompleter, language=None, taxon_id=taxon_id)
    if results:
        return [taxon.id for taxon in results]
    else:
        return []

def is_ancestor_match(top_id, selected_id, db_path=DB_PATH):
    """
    Checks if top_id is an ancestor of selected_id by checking the 
    comma-delimited ancestor_ids string in the local taxon table.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ancestor_ids FROM taxon WHERE id = ?", (selected_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            ancestors = [int(x.strip()) for x in row[0].split(',') if x.strip().isdigit()]
            return top_id in ancestors
    except Exception as e:
        print(f"Warning: Ancestor check query failed ({e})")
    return False

def extract_and_evaluate_pairs(log_lines):
    print("Parsing logs for request pairs...")

    events = []
    for line in log_lines:
        match_ac = RE_AUTOCOMPLETE.search(line)
        if match_ac:
            d = match_ac.groupdict()
            parsed_params = parse_qs(d['querystring'])

            q_values = parsed_params.get('q', [''])
            raw_query = q_values[0] if q_values else ''
            decoded_query = unquote(raw_query).replace('+', ' ').lower().strip()

            if RE_DISCARD.search(decoded_query):
                continue

            taxon_id_values = parsed_params.get('taxon_id', [None])
            req_taxon_id = int(taxon_id_values[0]) if taxon_id_values[0] else None

            # Extract locale parameter if present
            locale_values = parsed_params.get('locale', [None])
            locale = locale_values[0] if locale_values[0] else None

            # Discard scientific locale tests per dronefly-core special casing
            # - In dronefly-core, match_taxon gives scientific names a bump
            #   and that messes with our evaluation of the FTS autocomplete
            #   vs. pure iNat API /v1/taxa/autocomplete as our reference
            #   implementation we're striving to reach parity with.
            if locale == 'sci':
                continue
            events.append({
                'type': 'autocomplete',
                'time': parse_log_timestamp(d['timestamp']),
                'query': decoded_query,
                'param_taxon_id': req_taxon_id,
                'locale': locale
            })
            continue

        match_dt = RE_TAXON_DETAIL.search(line)
        if match_dt:
            d = match_dt.groupdict()
            events.append({
                'type': 'taxon_detail',
                'time': parse_log_timestamp(d['timestamp']),
                'taxon_id': int(d['taxon_id'])
            })

    # Sort events chronologically
    events.sort(key=lambda x: x['time'])

    pairs = []
    i = 0
    while i < len(events):
        if events[i]['type'] == 'autocomplete':
            # Collect a contiguous batch of back-to-back autocomplete events
            batch_acs = []
            j = i
            while j < len(events) and events[j]['type'] == 'autocomplete':
                # Ensure they happen tightly together (e.g., within 1 second of the start or previous)
                if batch_acs and (events[j]['time'] - batch_acs[-1]['time']) > timedelta(seconds=1):
                    break
                batch_acs.append(events[j])
                j += 1

            # If we collected 2 or more autocompletes in a row...
            if len(batch_acs) >= 2:
                # Check if they are followed immediately by a taxon_detail call within 1 second
                if j < len(events) and events[j]['type'] == 'taxon_detail':
                    dt_event = events[j]
                    if (dt_event['time'] - batch_acs[-1]['time']) <= timedelta(seconds=1):
                        # This is a multi-query batch (like 'related X,Y'). 
                        # The detail call is a common ancestor, not a direct selection for either query.
                        # Skip/discard these so they don't trigger false MISSING flags.
                        i = j + 1
                        continue

            # Otherwise, check for standard triad or single pair logic as before...
            # - these result from `,t related`. actually instead of a triad you can
            #   have an arbitrary number of related but:
            #   - triads are the norm (autocomplete?q=text1, autocomplete?q=text2, taxa/#)
            #   - detection of a final triad is sufficient to find and throw out this case,
            #     (i.e. don't count as a pair)
            #   - we can't use it because the matched taxon id# doesn't line up with any
            #     one string that was searched, but only to their children, and unfortunately
            #     the logs don't have those intermediate results
            ac1 = batch_acs[0]

            # Check for Triad: ac1 -> ac2 (with param_taxon_id) -> dt
            if (i + 2 < len(events) and 
                events[i+1]['type'] == 'autocomplete' and 
                events[i+1].get('param_taxon_id') is not None and 
                events[i+2]['type'] == 'taxon_detail' and 
                (events[i+1]['time'] - ac1['time']) <= timedelta(seconds=1) and 
                (events[i+2]['time'] - events[i+1]['time']) <= timedelta(seconds=1)):

                ac2 = events[i+1]
                dt = events[i+2]
                parent_id = ac2['param_taxon_id']

                pairs.append({
                    'query': ac1['query'],
                    'selected_taxon_id': parent_id,
                    'parent_taxon_id': None,
                    'timestamp': ac1['time'].isoformat(),
                    'locale': ac1.get('locale')
                })
                pairs.append({
                    'query': ac2['query'],
                    'selected_taxon_id': dt['taxon_id'],
                    'parent_taxon_id': parent_id,
                    'timestamp': ac2['time'].isoformat(),
                    'locale': ac2.get('locale')
                })
                i += 3
                continue

            # Standard single pair check (ac1 -> dt)
            k = i + 1
            matched_standard = False
            while k < len(events):
                next_event = events[k]
                if (next_event['time'] - ac1['time']) > timedelta(seconds=1):
                    break
                if next_event['type'] == 'taxon_detail':
                    pairs.append({
                        'query': ac1['query'],
                        'selected_taxon_id': next_event['taxon_id'],
                        'parent_taxon_id': None,
                        'timestamp': ac1['time'].isoformat(),
                        'locale': ac1.get('locale')
                    })
                    matched_standard = True
                    i = k + 1
                    break
                elif next_event['type'] == 'autocomplete':
                    break
                k += 1

            if matched_standard:
                continue

        i += 1

    print(f"Extracted {len(pairs):,} strict query-selection pairs (including triads).")
    return pairs

def get_local_max_taxon_id(db_path=DB_PATH):
    """Finds the highest taxon ID present in the local SQLite mirror."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(id) FROM taxon")
        max_id = cursor.fetchone()[0]
        conn.close()
        return max_id or 0
    except Exception as e:
        print(f"Warning: Could not read local DB max ID ({e})")
        return 0

def main():
    # Option 1: Read from journalctl stream or a saved log dump file if available.
    print("Fetching logs from journalctl...")
    # - All Dronefly & SeedWasp logs until 2026-10-22T07:00 so we can compare subsequent
    #   runs on the same full data set without more recent entries added to it.
    cmd = ["journalctl", "--unit", "red@Dronefly", "--unit", "red@SeedWasp", "--until", "2026-10-22T07:00"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        log_lines = result.stdout.splitlines()
    except Exception as e:
        print(f"Error running journalctl: {e}")
        sys.exit(1)

    # Get the local max ID ceiling from taxa.db
    local_max_id = get_local_max_taxon_id()
    print(f"Local database taxon ID ceiling: {local_max_id:,}")

    pairs = extract_and_evaluate_pairs(log_lines)

    evaluated_rows = []
    not_found_count = 0
    rank_distribution = {1: 0, "2-5": 0, "6-10": 0, ">10": 0}

    missing_records_for_batch = []

    for p in pairs:
        query = p['query']
        selected_id = int(p['selected_taxon_id'])
        parent_id = p['parent_taxon_id']
        timestamp = p['timestamp']
        locale = p.get('locale')

        results = taxon_autocomplete(text=query, autocompleter=autocompleter, language=locale, taxon_id=parent_id)
        result_ids = [taxon.id for taxon in results] if results else []

        rank = None
        matched_as_ancestor = False
        resolved_taxon_id = selected_id

        if result_ids:
            if selected_id in result_ids:
                rank = result_ids.index(selected_id) + 1
                resolved_taxon_id = selected_id
            else:
                for idx, r_id in enumerate(result_ids):
                    if is_ancestor_match(r_id, selected_id):
                        rank = idx + 1
                        matched_as_ancestor = True
                        resolved_taxon_id = r_id
                        break

        row_data = {
            'query': query,
            'selected_taxon_id': resolved_taxon_id,
            'parent_taxon_id': parent_id if parent_id is not None else '',
            'timestamp': timestamp,
            'rank': rank,
            'is_ancestor_match': matched_as_ancestor
        }

        if rank is not None:
            if rank == 1:
                rank_distribution[1] += 1
            elif 2 <= rank <= 5:
                rank_distribution["2-5"] += 1
            elif 6 <= rank <= 10:
                rank_distribution["6-10"] += 1
            else:
                rank_distribution[">10"] += 1

            row_data['rank_position'] = f"{rank} (ancestor)" if matched_as_ancestor else rank
            evaluated_rows.append(row_data)
        else:
            if selected_id > local_max_id:
                row_data['rank_position'] = f'FILTERED (post-snapshot ID {selected_id:,} > max {local_max_id:,})'
                evaluated_rows.append(row_data)
            else:
                missing_records_for_batch.append(row_data)

    # Save to CSV
    csv_path = Path(OUTPUT_CSV)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['query', 'selected_taxon_id', 'parent_taxon_id', 'rank_position', 'timestamp']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        clean_rows = [{k: v for k, v in row.items() if k in fieldnames} for row in evaluated_rows]
        writer.writerows(clean_rows)

    print(f"\nEvaluation complete! Saved {len(clean_rows):,} rows to {OUTPUT_CSV}")
    print(f"  - True missing from result list: {not_found_count:,}")
    print("  - Rank Breakdown:")
    for k, v in rank_distribution.items():
        print(f"    * Position {k}: {v:,}")

if __name__ == "__main__":
    main()
