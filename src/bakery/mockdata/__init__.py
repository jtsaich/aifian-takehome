"""Mock 範本 files, store uploads, legacy files and the 對照表 for the demo and tests.

    from bakery.mockdata import generate_mock_data
    manifest = generate_mock_data(tmp_path, seed=DEFAULT_SEED, today=date(2026, 10, 21))

Same seed + same today => byte-identical files.
"""

from bakery.mockdata.expectations import Manifest
from bakery.mockdata.scenarios import ASSUMPTIONS
from bakery.mockdata.scenarios import generate as generate_mock_data

DEFAULT_SEED = 2026
DEFAULT_OUT_DIR = "mock_data"

__all__ = ["ASSUMPTIONS", "DEFAULT_OUT_DIR", "DEFAULT_SEED", "Manifest", "generate_mock_data"]
