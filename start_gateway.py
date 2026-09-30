"""Gateway entry for ACLClouds: PY_FILE=start_gateway.py"""
from main import ensure_deps, load_dotenv

load_dotenv()
ensure_deps()

from legion_api import LegionApi
from report_listener import run_gateway

run_gateway(LegionApi())
