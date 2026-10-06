from dataclasses import dataclass


@dataclass
class Config:
    scale: float = 1024          # channel value that maps to +/-1.0
    stale_ms: int = 500          # no control sample for this long = paused
    arm_threshold: int = 0
    crash_threshold: int = 0
    input_label: str = 'unknown'  # sticks | outputs | unknown (when hello doesn't say)
    demo: bool = False           # marks snapshots as synthetic ('demo' status)
