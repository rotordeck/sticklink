from dataclasses import dataclass


@dataclass
class Config:
    scale: float = 1024          # channel value that maps to +/-1.0
    stale_ms: int = 500          # no control sample for this long = paused
    arm_threshold: int = 0
    crash_threshold: int = 0
    race_double_tap_ms: int = 500  # two crash-flip taps this close together stop the race timer
    input_label: str = 'unknown'  # sticks | outputs | unknown (when hello doesn't say)
    demo: bool = False           # marks snapshots as synthetic ('demo' status)
