import re
import os
import sys
import gzip
import bz2
import json
import requests
from typing import Callable, Optional, Generator, Union, Any, Dict, List
from pathlib import Path
from urllib.parse import unquote

# ============================= INITIALIZATION ==================================== #
from SciXPipelineUtils.utils import load_config

proj_home = os.path.realpath(os.path.join(os.path.dirname(__file__), "../"))
config = load_config(proj_home=proj_home)

def normalize_doi(doi: str) -> str:
    """Normalize a DOI for case-insensitive, prefix-agnostic comparison."""
    doi = doi.strip()
    doi = re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)', '', doi, flags=re.IGNORECASE)
    doi = doi.lower()
    doi = unquote(doi)
    return doi


def casefold_key(value: str) -> str:
    """Case-insensitive comparison only �~@~T for bibcode files sorted with sort -f."""
    return value.strip().lower()


def identity_key(value: str) -> str:
    """No normalization �~@~T exact, case-sensitive match."""
    return value.strip()


def _seek_to_line_start(f, pos: int) -> int:
    """
    Seek to pos, then advance to the start of the next full line,
    unless pos is already exactly the start of a line.
    Returns the resulting (line-start) byte offset.
    """
    if pos == 0:
        f.seek(0)
        return 0
    f.seek(pos - 1)
    prev_byte = f.read(1)
    if prev_byte == b"\n":
        f.seek(pos)
        return pos  # already at a line boundary �~@~T don't skip anything
    f.readline()  # consume partial line fragment
    return f.tell()

def find_all(
    filepath: str,
    target: str,
    key_func: Callable[[str], str] = identity_key,
) -> List[str]:
    """
    Binary search a tab-separated file sorted (according to key_func's
    notion of order) on column 0. Returns ALL matching lines, or [].

    key_func examples:
      - normalize_doi  : for DOI columns (case-insensitive, strips prefixes,
                          decodes percent-encoding)
      - casefold_key   : for bibcode files sorted with `sort -f`
                          (case-insensitive, no other normalization)
      - identity_key   : for exact, case-sensitive matching
    """
    target_norm = key_func(target)

    with open(filepath, "rb") as f:
        f.seek(0, 2)
        file_size = f.tell()

        lo, hi = 0, file_size
        result_pos = -1

        # --- Binary search for *any* matching line ---
        while lo < hi:
            mid = (lo + hi) // 2
            line_start = _seek_to_line_start(f, mid)
            f.seek(line_start)

            raw = f.readline()
            if not raw:
                hi = mid
                continue

            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            key = key_func(line.split("\t", 1)[0])

            if key < target_norm:
                lo = line_start + len(raw)
            else:
                if key == target_norm:
                    result_pos = line_start
                hi = mid
        if result_pos == -1:
            return []

        # --- Walk backward to find the START of the matching run ---
        first_pos = result_pos
        while first_pos > 0:
            step = min(first_pos, 4096)
            f.seek(first_pos - step)
            chunk = f.read(step)
            nl = chunk.rfind(b"\n", 0, -1)
            prev_start = first_pos - step + nl + 1 if nl != -1 else 0
            f.seek(prev_start)
            raw = f.readline()
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            key = key_func(line.split("\t", 1)[0])
            if key != target_norm:
                break
            first_pos = prev_start

        # --- Walk forward from first_pos, collecting all matching lines ---
        matches = []
        f.seek(first_pos)
        while True:
            raw = f.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            key = key_func(line.split("\t", 1)[0])
            if key != target_norm:
                break
            matches.append(line)

        return matches

def find_first(
    filepath: str,
    target: str,
    key_func: Callable[[str], str] = identity_key,
) -> Optional[str]:
    """Convenience wrapper returning just the first match, or None."""
    matches = find_all(filepath, target, key_func=key_func)
    return matches[0] if matches else None

def extract_doi(s: str) -> Optional[str]:
    """
    Given a string, determine if it contains a DOI (bare or URL form)
    and return the bare DOI, or None if not found.

    Handles:
      - Bare DOI:  10.1234/something
      - HTTPS URL: https://doi.org/10.1234/something
      - HTTP URL:  http://doi.org/10.1234/something
      - dx.doi.org variants
      - Leading/trailing whitespace
    """
    s = s.strip()

    # Canonical DOI pattern: registrant prefix (10.NNNN) + slash + suffix
    # The suffix can contain almost anything except whitespace
    DOI_RE = re.compile(
        r'\b(10\.\d{4,9}/[^\s"\'<>]+)',
        re.IGNORECASE,
    )

    match = DOI_RE.search(s)
    if match:
        doi = match.group(1)
        # Strip trailing punctuation that is unlikely to be part of the DOI
        doi = doi.rstrip('.,;:)')
        return doi

    return None

def is_doi(s: str) -> bool:
    """Returns True if the string is a bare DOI (e.g. '10.1234/suffix')."""
    return bool(re.match(r'^10\.\d{4,9}/.+$', s.strip()))

def has_non_ascii(s: str) -> bool:
    """Returns True if the string contains any non-ASCII characters."""
    return not s.isascii()

def open_compressed_jsonl(filepath: Union[str, Path]) -> Generator[Dict[str, Any], None, None]:
    """
    Opens a compressed or uncompressed JSONL file and returns a generator
    that yields JSON objects.
    """
    if filepath.endswith('.gz'):
        with gzip.open(filepath, 'rt', encoding='utf-8') as file:
            for line in file:
                yield json.loads(line)
    else:
        with open(filepath, 'r', encoding='utf-8') as file:
            for line in file:
                yield json.loads(line)

def get_doi_registration_agency(doi: str) -> str:
    """
    Query the DOI RA API to find where a DOI is registered.

    Returns info about the registration agency (e.g., Crossref, DataCite, mEDRA).
    """
    # Clean the DOI strip URL prefix if present
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    elif doi.startswith("http://doi.org/"):
        doi = doi[len("http://doi.org/"):]

    url = "https://doi.org/doiRA/{0}".format(doi)

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    return data[0] if isinstance(data, list) else data

def get_resource_type_local(doi: str) -> str:

    doi_field = {
        'Crossref':'DOI',
        'DataCite':'id'
    }

    local_data = get_local_data(doi)

    try:
        datafile = local_data.split('\t')[1]
    except:
        return 'NA'

    rec_data = {}
    source = 'DataCite'
    if '/Crossref/' in datafile:
        source = 'Crossref'
    for data in open_compressed_jsonl(datafile):
        if doi.lower() ==  data[doi_field[source]].lower():
            rec_data = data
            break
    restype = 'NA'
    if rec_data:
        if source == 'Crossref':
            restype = rec_data['type']
        else:
            try:
                restype = rec_data['attributes']['types']['resourceTypeGeneral']
            except:
                pass
    return restype


def get_universal_resource_type(dlink: str) -> str:
    """
    Attempts to find resource type from Crossref,
    falling back to DataCite if not found.

    param: dlink: data link provided
    """
    # Attempt to extract DOI
    try:
        doi = extract_doi(dlink)
    except:
        doi = None
    # If we did not get a DOI, we can leave now
    if not doi:
        if dlink.startswith('http'):
            return "URL"
        else:
            return "NA"
    # We have a DOI!
    # 0. Try local data first
    try:
        restype = get_resource_type_local(doi)
        if restype != 'NA':
            return restype
    except:
        pass
    # 0. Funder DOIs (in Crossref funder registry)
    if doi.startswith('10.13039/'):
        return "Crossref: funder"
    # 1. Next try Crossref
    headers = {
        "Crossref-Plus-API-Token": config['CROSSREF_API_TOKEN'],
        "User-Agent": config['CROSSREF_USER_AGENT']
    }
    crossref_url = "https://api.crossref.org/works/{0}".format(doi)
    err = 'NA'
    try:
        cr_resp = requests.get(crossref_url, headers=headers, timeout=5)
        if cr_resp.status_code == 200:
            data = cr_resp.json()
            return data.get('message', {}).get('type', 'unknown')
    except Exception as err:
        pass # Silently fail to move to next provider

    # 2. Try DataCite as fallback
    datacite_url = "https://api.datacite.org/dois/{0}".format(doi)
    try:
        dc_resp = requests.get(datacite_url, timeout=5)
        if dc_resp.status_code == 200:
            data = dc_resp.json()
            gen_type = data.get("data", {}).get("attributes", {}).get("types", {}).get("resourceTypeGeneral", "unknown")
            return gen_type
    except Exception as err:
        pass

    # 3. DOI is not registered with either Crossref or DataCite: just return the agency
    try:
        result = get_doi_registration_agency(doi)
        resp = "registry: {0}".format(result.get('RA'))
        return resp
    except Exception as err:
        pass
    return err

def get_references_from_file(reference_file, bibcode):
    resol_file = reference_file.replace('sources','resolved') + ".result"
    refs = []
    try:
        fdesc = open(resol_file)
    except IOError:
        # Something is wrong with the reference file for this bibcode, warn but no longer fail
        sys.stderr.write('%s missing reference file %s\n' % (bibcode, resol_file))
        return []

    # First find the start of the reference section.
    for line in fdesc:
        if line.startswith('---<'):
            mat = re.match('<(.*?)>', line[3:])
            if mat:
                citing_bib = mat.group(1)
                if bibcode == citing_bib:
                    break
    else:
        # Bibcode not found.
        return 0

    for index, line in enumerate(fdesc):
#        refs.append(line[25:].strip())
        refs.append(line.strip())
        if line.startswith('---<'):
            # Start of a new reference block.
            break
    return refs
