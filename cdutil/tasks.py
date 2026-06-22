import os
import sys
import requests
import json
from typing import List, Optional, Callable
from urllib.parse import unquote
import re

import cdutil.utils as utils

# ============================= INITIALIZATION ==================================== #
from SciXPipelineUtils.utils import load_config

proj_home = os.path.realpath(os.path.join(os.path.dirname(__file__), "../"))
config = load_config(proj_home=proj_home)
# =============================== FUNCTIONS ======================================= #
def casefold_key(value: str) -> str:
    """Case-insensitive comparison only �~@~T for bibcode files sorted with sort -f."""
    return value.strip().lower()

def get_ft_files(bbc):
    res = utils.find_all(config['FULLTEXT_MAP'], bbc, key_func=casefold_key)
    return res

def get_ref_files(bbc, source=None):
    results = []
    res = utils.find_all(config['REFERENCES_MAP'], bbc, key_func=casefold_key)
    if source == 'Crossref':
        res = [e for e in res if e.split('\t')[1].endswith('xref.xml')]
    if source == 'Publisher':
        jnl = bbc[4:9].replace('.','')
        res = [e for e in res if not e.split('\t')[1].endswith('xref.xml') and e.split('\t')[1].startswith(jnl)]
    for entry in res:
        results.append("{0}/{1}".format(config['REF_SRC_BASE'], entry.split('\t')[1]))
    return results

def get_cited_ids(bbc, skip_matched=True):
    res = utils.find_all(config['REFIDS_MAP'], bbc, key_func=casefold_key)
    dois = []
    seen = set()
    for entry in res:
        b, ref = entry.strip().split('\t')
        rdata = json.loads(ref)
        if rdata['score'] == '1' and skip_matched:
            continue
        try:
            doi = rdata['doi']
            if doi in seen:
                continue
            seen.add(doi)
            dtype = utils.get_universal_resource_type(doi)
            dois.append("{0} | {1}".format(doi, dtype))
        except:
            pass
    return dois

def get_record(identifier, fl='*'):
    q = 'identifier:{0}'.format(identifier)
    solr_args = {'wt': 'json', 'q': q, 'fl': fl, 'rows': 100000}
    headers = {'Authorization': 'Bearer %s' % config.get('ADS_API_TOKEN', '')}
    response = requests.get(
        config.get('ADS_SOLR_PATH'),
        params=solr_args,
        headers=headers)
    if response.status_code != 200:
        return None
    resp = response.json()
    return resp['response']['docs'][0]

def get_summary_overview(identifier):

    results = {}
    rec = get_record(identifier)
    bibcode = rec['bibcode']
    ft_files = get_ft_files(bibcode)
    ref_files = get_ref_files(bibcode)
    ref_ids = get_cited_ids(bibcode)

    results['supplied_id'] = identifier
    results['acknowledgements'] = 'Not Available'
    if 'ack' in rec:
        results['acknowledgements'] = rec['ack']
    results['preprint'] = 'No match'
    for ident in rec['identifier']:
        if ident.lower().startswith('arxiv:'):
            results['preprint'] = ident
    results['bibcode'] = bibcode
    results['alternates'] = 'None'
    if 'alternate_bibcode' in rec:
        results['alternates'] = ", ".join(rec['alternate_bibcode'])
    results['doi'] = ", ".join(rec['doi'])
    results['identifier'] = ", ".join(rec['identifier'])
    results['scix_id'] = rec.get('scix_id','Not Available')
    results['fulltext'] = []
    for entry in ft_files:
        results['fulltext'].append(entry.split('\t')[1])
    results['references'] = ref_files
    results['refids'] = ", ".join(ref_ids)

    return results

def get_references(identifier):
    Crossref = {}
    Publisher = {}
    rec = get_record(identifier)
    bibcode = rec['bibcode']

    Crossref['source'] = 'Crossref'
    Crossref['bibcode'] = bibcode
    Publisher['source'] = 'Publisher'
    Publisher['bibcode'] = bibcode

    cr_files = get_ref_files(bibcode, source='Crossref')
    pub_files= get_ref_files(bibcode, source='Publisher')
   
    for rfile in cr_files:
        Crossref[rfile] = []
        refs = utils.get_references_from_file(rfile, bibcode)
        for ref in refs:
            Crossref[rfile].append(ref)
    for rfile in pub_files:
        Publisher[rfile] = []
        refs = utils.get_references_from_file(rfile, bibcode)
        for ref in refs:
            Publisher[rfile].append(ref)
    return Publisher, Crossref

def _format_summary_stdout(results):
    lines = []
    lines.append("Summary Overview for ID: {0}".format(results['supplied_id']))
    lines.append("")
    lines.append("supplied id:        {0}".format(results['supplied_id']))
    lines.append("canonical bibcode:  {0}".format(results['bibcode']))
    lines.append("matched preprint:   {0}".format(results['preprint']))
    lines.append("alternates:         {0}".format(results['alternates']))
    lines.append("doi:                {0}".format(results['doi']))
    lines.append("identifiers:        {0}".format(results['identifier']))
    lines.append("SciX ID:            {0}".format(results['scix_id']))
    lines.append("unmatched DOI cites:{0}".format(results['refids']))
    lines.append("fulltext sources:")
    for f in results['fulltext']:
        lines.append("    {0}".format(f))
    lines.append("reference sources:")
    for f in results['references']:
        lines.append("    {0}".format(f))
    lines.append("acknowledgements:")
    ack = results['acknowledgements']
    if isinstance(ack, list):
        for entry in ack:
            lines.append("    {0}".format(entry))
    else:
        lines.append("    {0}".format(ack))
    return "\n".join(lines)

def _normalize_match(match):
    if match is None:
        return None
    if match in ('1', 'resolved'):
        return '1'
    if match in ('5', 'guessed'):
        return '5'
    if match in ('0', 'unmatched'):
        return '0'
    return None


def _format_references_stdout(source_dict, match=None):
    lines = []
    source = source_dict['source']
    bibcode = source_dict['bibcode']
    skip_keys = {'source', 'bibcode'}
    lines.append("# {0} references for citing bibcode: {1}".format(source, bibcode))
    for rfile, refs in source_dict.items():
        if rfile in skip_keys:
            continue
        lines.append("## Reference source: {0}".format(rfile))
        matched = [r[2:] for r in refs if r.startswith("1 ")]
        guessed = [r[2:] for r in refs if r.startswith("5 ")]
        no_match = [r[2:] for r in refs if r.startswith("0 ")]
        if match is None or match == '1':
            lines.append("### Matched references")
            lines.extend(matched)
        if match is None or match == '5':
            lines.append("### Unmatched references (guessed)")
            lines.extend(guessed)
        if match is None or match == '0':
            lines.append("### Unmatched references (no match)")
            lines.extend(no_match)
    return "\n".join(lines)


def export_results(action, results, fmt, source=None, match=None):
    if action == 'summary':
        if fmt == 'stdout':
            print(_format_summary_stdout(results))
    elif action == 'references':
        if fmt == 'stdout':
            Publisher, Crossref = results
            match_code = _normalize_match(match)
            if source != 'Crossref':
                print(_format_references_stdout(Publisher, match=match_code))
            if source != 'Publisher':
                if source != 'Crossref':
                    print()
                print(_format_references_stdout(Crossref, match=match_code))
