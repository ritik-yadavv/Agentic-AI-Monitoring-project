from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..config import MonitorConfig
from ..models import Finding, Trace


class Detector(ABC):
    """A detector is a pure function Trace -> [Finding]. Detectors are independent of each other."""

    mode = "unknown"

    def __init__(self, config: MonitorConfig):
        self.cfg = config

    @abstractmethod
    def detect(self, trace: Trace) -> List[Finding]:
        raise NotImplementedError
