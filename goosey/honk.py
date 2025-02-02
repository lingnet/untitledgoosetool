#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Untitled Goose Tool: Honk!
This module performs data collection of various data sources from an Azure/M365 environment.
"""

import aiohttp
import argparse
import asyncio
import configparser
import json
import os
import sys
import time
import warnings

from goosey.auth import check_token
from goosey.azure_ad_datadumper import AzureAdDataDumper
from goosey.azure_dumper import AzureDataDumper
from goosey.datadumper import DataDumper
from goosey.m365_datadumper import M365DataDumper
from goosey.mde_datadumper import MDEDataDumper
from goosey.utils import *

__author__ = "Claire Casalnova, Jordan Eberst, Wellington Lee, Victoria Wallace"
__version__ = "1.0.0"

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

warnings.simplefilter('ignore')

logger = None
data_calls = {}

def getargs(honk_parser) -> None:
    """Helper function to build arguments for argparse

    :param honk_parser: parser which will perform command line argument parsing
    :type honk_parser: argparse.ArgumentParser
    :return: None
    :rtype: None
    """
    honk_parser.add_argument('-a',
                               '--authfile',
                               action='store',
                               help='File to read credentials from obtained by goosey auth',
                               default='.ugt_auth')
    honk_parser.add_argument('-c',
                               '--config',
                               action='store',
                               help='Path to config file',
                               default='.conf')
    honk_parser.add_argument('--output-dir',
                               action='store',
                               help='Output directory for output files',
                               default='output')
    honk_parser.add_argument('--reports-dir',
                               action='store',
                               help='Output directory for output files',
                               default='reports')                               
    honk_parser.add_argument('--debug',
                               action='store_true',
                               help='Debug output',
                               default=False)
    honk_parser.add_argument('--dry-run',
                               action='store_true',
                               help='Dry run (do not do any API calls)',
                               default=False)
    honk_parser.add_argument('--azure',
                                action='store_true',
                                help='Set all of the azure calls to true',
                                default=False)
    honk_parser.add_argument('--ad',
                                action='store_true',
                                help='Set all of the Azure AD calls to true',
                                default=False)   
    honk_parser.add_argument('--m365',
                                action='store_true',
                                help='Set all of the M365 calls to true',
                                default=False)
    honk_parser.add_argument('--mde',
                                action='store_true',
                                help='Set all of the MDE calls to true',
                                default=False)

async def run(args, config, auth):
    """Main async run loop

    :param args: argparse object with populated namespace
    :type args: Namespace argparse object
    :param auth: All auth credentials
    :type auth: dict
    :return: None
    :rtype: None
    """
    global data_calls, logger

    session = aiohttp.ClientSession()

    msft_graph_auth = {}
    msft_graph_app_auth = {}

    for key in auth['mfa']:
        if 'graph.microsoft.com' in key or 'graph.microsoft.us' in key:
            msft_graph_auth = auth['mfa'][key]        

    for key in auth['app_auth']:
        if 'graph.microsoft.com' in key or 'graph.microsoft.us' in key:
            msft_graph_app_auth = auth['app_auth'][key]
        if 'management.azure.com' in key:
            mgmt_app_auth = auth['app_auth'][key]
        if 'api.securitycenter.microsoft.com' in key:
            msft_security_center_auth = auth['app_auth'][key]

    msft_graph_auth = check_token(config, msft_graph_auth, logger)

    maindumper = DataDumper(args.output_dir, args.reports_dir, msft_graph_auth, msft_graph_app_auth, session, args.debug)
    if args.dry_run:
        m365dumper = maindumper 
        azureaddumper = maindumper
        azure_dumper = maindumper
        mdedumper = maindumper
    else:
        m365dumper = M365DataDumper(args.output_dir, args.reports_dir, msft_graph_auth, msft_graph_app_auth, maindumper.ahsession, config, args.debug)
        azureaddumper = AzureAdDataDumper(args.output_dir, args.reports_dir, msft_graph_auth, msft_graph_app_auth, maindumper.ahsession, config, args.debug)
        azure_dumper = AzureDataDumper(args.output_dir, args.reports_dir, maindumper.ahsession, mgmt_app_auth, config, args.debug)
        mdedumper = MDEDataDumper(args.output_dir, args.reports_dir, msft_graph_auth, msft_security_center_auth, maindumper.ahsession, config, args.debug)

    async with maindumper.ahsession as ahsession:

        tasks = []
        tasks.extend(azure_dumper.data_dump(data_calls['azure']))
        tasks.extend(m365dumper.data_dump(data_calls['m365']))
        tasks.extend(azureaddumper.data_dump(data_calls['azuread']))
        tasks.extend(mdedumper.data_dump(data_calls['mde']))
        
        await asyncio.gather(*tasks)

def _get_section_dict(config, s):
    try:
        return dict([(x[0], x[1].lower()=='true') for x in config.items(s)])
    except Exception as e:
        logger.warning(f'Error getting section dictionary from config: {str(e)}')
    return {}

def parse_config(configfile, args):
    global data_calls
    config = configparser.ConfigParser()
    config.read(configfile)

    sections = ['azure', 'm365', 'azuread', 'mde']

    for section in sections:
        d = _get_section_dict(config, section)
        data_calls[section] = {}
        for key in d:
            if d[key]:
                data_calls[section][key] = True
    
    if args.azure:
        for item in [x.replace('dump_', '') for x in dir(AzureDataDumper) if x.startswith('dump_')]:
            data_calls['azure'][item] = True
    if args.ad:
        for item in [x.replace('dump_', '') for x in dir(AzureAdDataDumper) if x.startswith('dump_')]:
            data_calls['azuread'][item] = True
    if args.m365:
        for item in [x.replace('dump_', '') for x in dir(M365DataDumper) if x.startswith('dump_')]:
            data_calls['m365'][item] = True
    if args.mde:
        for item in [x.replace('dump_', '') for x in dir(MDEDataDumper) if x.startswith('dump_')]:
            data_calls['mde'][item] = True


    logger.debug(json.dumps(data_calls, indent=2))
    return config
        
def main(args=None, gui=False) -> None:
    global logger

    parser = argparse.ArgumentParser(add_help=True, description='Goosey', formatter_class=argparse.RawDescriptionHelpFormatter)

    getargs(parser)

    if args is None:
        args = parser.parse_args()

    if gui:
        logger = setup_logger(__name__, args.debug, formatter='gui')
    else:
        logger = setup_logger(__name__, args.debug)

    if not os.path.isfile(args.authfile):
        logger.warning("{} auth file missing. Please auth first. Exiting.".format(args.authfile))
        sys.exit(1)

    auth = {}
    try:
        logger.info("Reading in authfile: {}".format(args.authfile))
        with open(args.authfile, 'r') as infile:
            auth = json.loads(infile.read())
    except Exception as e:
        logger.error("{}".format(str(e)))
        raise e

    check_output_dir(args.output_dir, logger)
    check_output_dir(args.reports_dir, logger)
    check_output_dir(f'{args.output_dir}{os.path.sep}azure', logger)
    check_output_dir(f'{args.output_dir}{os.path.sep}m365', logger)
    check_output_dir(f'{args.output_dir}{os.path.sep}azuread', logger)
    check_output_dir(f'{args.output_dir}{os.path.sep}mde', logger)
    config = parse_config(args.config, args)

    logger.info("Goosey beginning to honk.")
    seconds = time.perf_counter()
    asyncio.run(run(args, config, auth))
    elapsed = time.perf_counter() - seconds
    logger.info("Goosey executed in {0:0.2f} seconds.".format(elapsed))

if __name__ == "__main__":
    main()
