from __future__ import print_function
import argparse
import datetime
import sys
import os

from cdutil import tasks

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# ============================= INITIALIZATION ==================================== #
from SciXPipelineUtils.utils import load_config

proj_home = os.path.realpath(os.path.join(os.path.dirname(__file__), "./"))
config = load_config(proj_home=proj_home)
# =============================== FUNCTIONS ======================================= #

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Process user input.')
    subparsers = parser.add_subparsers(help='commands', dest="action", required=True)

    summary = subparsers.add_parser('summary', help='Show data summary')
    summary.add_argument('-i', '--identifier', dest='identifier',
                        help='Report for identifier given (DOI or bibcode)')
    summary.add_argument('-o', '--output', default='stdout', dest='output',
                        help='Output destination')

    references = subparsers.add_parser('references', help='Display references')
    references.add_argument('-i', '--identifier', dest='identifier',
                        help='Report for identifier given (DOI or bibcode)')
    references.add_argument('-o', '--output', default='stdout', dest='output',
                        help='Output destination')
    references.add_argument('-s', '--source', dest='source', choices=['Publisher', 'Crossref'],
                        help='Show only Publisher or Crossref references')
    references.add_argument('-m', '--match', dest='match',
                        help='Filter by match status: resolved/1, guessed/5, unmatched/0')

#    fulltext = subparsers.add_parser('fulltext', help='Display fulltext')
#    fulltext.add_argument('-i', '--identifier', dest='identifier',
#                        help='Report for identifier given (DOI or bibcode)')
#    fulltext.add_argument('-o', '--output', default='stdout', dest='output',
#                        help='Output destination')

    args = parser.parse_args()

    if not args.identifier:
        sys.exit('Please specify an identifier (DOI, bibcode) using -i')
 
    if args.action == 'summary':
        res = tasks.get_summary_overview(args.identifier)
    elif args.action == 'references':
        res = tasks.get_references(args.identifier)

    tasks.export_results(args.action, res, args.output,
                         source=getattr(args, 'source', None),
                         match=getattr(args, 'match', None))

