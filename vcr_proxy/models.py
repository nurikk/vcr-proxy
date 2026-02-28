# vcr_proxy/models.py — minimal version needed for config
from enum import StrEnum


class ProxyMode(StrEnum):
    RECORD = "record"
    REPLAY = "replay"
    SPY = "spy"
