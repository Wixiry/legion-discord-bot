"""Gateway entry for Bothost / ACLClouds: CMD python start_gateway.py"""
try:
    from dotenv import load_dotenv as _dotenv_load
    _dotenv_load()
except ImportError:
    pass

from main import ensure_deps, load_dotenv

load_dotenv()
ensure_deps()

from legion_api import LegionApi
from report_listener import run_gateway

run_gateway(LegionApi())
