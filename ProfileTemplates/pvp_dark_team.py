import json
import os
import re
import time
import requests

DATA_PATH = r"c:\Users\cwjki\OneDrive\Documents\git\Backup\pretty_scan_data.json"
CACHE_PATH = r"c:\Users\cwjki\OneDrive\Documents\git\Backup\pokedex_type_cache.json"
TOP_N = 12

def load_data(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def normalize_name(n):
    if not isinstance(n, str):
        return None
    s = n.strip().lower()
    s = re.sub(r"[ \._']", "-", s)
    s = re.sub(r"[^a-z0-9\-\:]+", "", s)  # allow basic chars and hyphen
    return s

def get_pokemon_name(entry):
    for k in ("name", "pokemon", "species", "pokedexName", "pokeName", "pokemonName"):
        if k in entry and entry[k]:
            return entry[k]
    # try infer from imageId or id if no visible name
    return entry.get("name") or entry.get("id") or None

def fetch_types_from_api(name):
    n = normalize_name(name)
    if not n:
        return []
    url = f"https://pokeapi.co/api/v2/pokemon/{n}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            j = r.json()
            types = [t["type"]["name"].lower() for t in sorted(j["types"], key=lambda x: x["slot"])]
            return types
    except Exception:
        pass
    # try fallback: remove suffixes like '-galar' or '-alola'
    n2 = re.sub(r"-(galar|alola|hisui|galarian|alolan|origin|zen)", "", n)
    if n2 != n:
        try:
            r = requests.get(f"https://pokeapi.co/api/v2/pokemon/{n2}", timeout=10)
            if r.status_code == 200:
                j = r.json()
                types = [t["type"]["name"].lower() for t in sorted(j["types"], key=lambda x: x["slot"])]
                return types
        except Exception:
            pass
    return []

def get_types_for_name(name, cache):
    key = str(name).strip()
    if key in cache:
        return cache[key]
    types = fetch_types_from_api(name)
    cache[key] = types
    # be polite with API
    time.sleep(0.1)
    save_cache(cache)
    return types

def extract_pvp_score(entry, league):
    # try common keys present in exports
    # league: 'great' or 'ultra'
    # look for pvp fields in the entry
    # common patterns: 'pvpGreat', 'pvp_great', 'pvp' -> {'great':...}
    for k in entry:
        if isinstance(k, str) and 'pvp' in k.lower() and league in k.lower():
            try:
                v = entry[k]
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str) and v.replace('.','',1).isdigit():
                    return float(v)
            except Exception:
                pass
    # nested pvp object
    pvpo = entry.get("pvp") or entry.get("pvpInfo") or entry.get("pvpData")
    if isinstance(pvpo, dict):
        for subk in pvpo:
            if league in subk.lower():
                try:
                    return float(pvpo[subk])
                except Exception:
                    pass
        # direct keys 'great','ultra'
        if league in pvpo:
            try:
                return float(pvpo[league])
            except Exception:
                pass
    return None

def eligible_by_cp_for_league(entry, cap):
    # if max possible CP is present, use it; otherwise use current CP
    cp = entry.get("maxCPUpper") or entry.get("maxCPLower") or entry.get("maxCP") or entry.get("cp") or 0
    try:
        return float(cp) <= cap
    except Exception:
        return False

def pick_team(candidates, max_team=3):
    # Greedy choose by score while maximizing type diversity
    team = []
    used_types = set()
    for c in candidates:
        types = set(c["types"])
        if not types:
            # accept if still space
            if len(team) < max_team:
                team.append(c)
            continue
        # prefer candidates that add new types
        if not types.issubset(used_types) or len(team) < 1:
            team.append(c)
            used_types.update(types)
        if len(team) >= max_team:
            break
    return team

def summarize_list(lst):
    lines = []
    for i, e in enumerate(lst, 1):
        lines.append(f"{i}. {e['name']} — CP {e.get('cp', '?')}, IV% {e.get('ivPercentage', '?')}, types {e['types']}, pvp_great {e.get('pvp_great')}, pvp_ultra {e.get('pvp_ultra')}")
    return "\n".join(lines)

def main():
    print("Loading data...")
    data = load_data(DATA_PATH)
    cache = load_cache()
    dark_entries = []
    print("Scanning entries and resolving types (PokeAPI, cached)...")
    for entry in data:
        name = get_pokemon_name(entry)
        if not name:
            continue
        types = get_types_for_name(name, cache)
        if "dark" not in [t.lower() for t in types]:
            continue
        # extract pvp scores if present
        pvp_g = extract_pvp_score(entry, "great")
        pvp_u = extract_pvp_score(entry, "ultra")
        rec = {
            "name": name,
            "cp": entry.get("cp"),
            "ivPercentage": entry.get("ivPercentage"),
            "types": types,
            "pvp_great": pvp_g,
            "pvp_ultra": pvp_u,
            "entry": entry
        }
        dark_entries.append(rec)

    if not dark_entries:
        print("No Dark-type Pokémon found in your export (or PokeAPI name resolution failed).")
        return

    # Great League selection
    great_candidates = []
    for e in dark_entries:
        if eligible_by_cp_for_league(e["entry"], 1500):
            score = e["pvp_great"] if e["pvp_great"] is not None else (e["ivPercentage"] or 0)
            e["score_great"] = score
            great_candidates.append(e)
    great_sorted = sorted(great_candidates, key=lambda x: (x["score_great"] if x.get("score_great") is not None else 0), reverse=True)

    # Ultra League selection
    ultra_candidates = []
    for e in dark_entries:
        if eligible_by_cp_for_league(e["entry"], 2500):
            score = e["pvp_ultra"] if e["pvp_ultra"] is not None else (e["ivPercentage"] or 0)
            e["score_ultra"] = score
            ultra_candidates.append(e)
    ultra_sorted = sorted(ultra_candidates, key=lambda x: (x["score_ultra"] if x.get("score_ultra") is not None else 0), reverse=True)

    print("\nTop Great League Dark Pokémon (by pvp score or IV proxy):")
    print(summarize_list(great_sorted[:TOP_N]))

    print("\nTop Ultra League Dark Pokémon (by pvp score or IV proxy):")
    print(summarize_list(ultra_sorted[:TOP_N]))

    # Team compositions (pick 3)
    great_team = pick_team(great_sorted, 3)
    ultra_team = pick_team(ultra_sorted, 3)

    print("\nSuggested Great League team (diverse coverage):")
    print(summarize_list(great_team))

    print("\nSuggested Ultra League team (diverse coverage):")
    print(summarize_list(ultra_team))

if __name__ == "__main__":
    main()