from .looping import LoopDetector
from .tool_misuse import ToolMisuseDetector
from .hallucination import HallucinationDetector
from .goal_drift import GoalDriftDetector
from .unsafe import UnsafeActionDetector


def default_detectors(config):
    return [D(config) for D in (LoopDetector, ToolMisuseDetector, HallucinationDetector,
                                GoalDriftDetector, UnsafeActionDetector)]
