from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class Target:
    x: float
    y: float
    radius: float
    area: float
    quality: float = 1.0

    def distance(self, point):
        return math.hypot(self.x - point[0], self.y - point[1])


@dataclass
class Frame:
    image: Any
    timestamp: float
    sequence: int
    center: tuple[float, float]
    client_size: tuple[int, int]


@dataclass(frozen=True)
class Action:
    kind: str
    dx: int = 0
    dy: int = 0
    reason: str = ""
