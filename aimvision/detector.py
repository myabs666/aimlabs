import cv2
import numpy as np
from .model import Target


class Detector:
    def __init__(self, config):
        self.config = config

    def detect(self, frame):
        cfg = self.config
        source = frame.image
        width = source.shape[1]
        scale = min(1.0, cfg.detection_max_width / width) if cfg.detection_max_width else 1.0
        working = (cv2.resize(source, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                   if scale < 1.0 else source)
        hsv = cv2.cvtColor(working, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(cfg.hsv_low, dtype=np.uint8), np.array(cfg.hsv_high, dtype=np.uint8))
        # HUD exclusions are measured against the whole client, not against the cropped ROI.
        height = working.shape[0]
        offset_y = frame.client_size[1] / 2 - frame.center[1]
        top = max(0, min(height, int((frame.client_size[1] * cfg.exclude_top_fraction - offset_y) * scale)))
        bottom = max(0, min(height, int((frame.client_size[1] * (1 - cfg.exclude_bottom_fraction) - offset_y) * scale)))
        mask[:top] = 0
        mask[bottom:] = 0
        # Close small crosshair holes; no erosion, which would erase Sixshot-sized targets.
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        targets = []
        for contour in contours:
            working_area = cv2.contourArea(contour)
            area = working_area / (scale * scale)
            if area < cfg.min_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            circularity = 4 * np.pi * working_area / perimeter ** 2
            (working_x, working_y), working_radius = cv2.minEnclosingCircle(contour)
            x, y, radius = working_x / scale, working_y / scale, working_radius / scale
            if radius <= 0:
                continue
            fill = working_area / (np.pi * working_radius ** 2)
            bx, by, bw, bh = cv2.boundingRect(contour)
            if bx <= 0 or by <= 0 or bx + bw >= mask.shape[1] or by + bh >= mask.shape[0]:
                continue  # A cropped circle has an unreliable center.
            ratio = bw / bh
            if (area <= cfg.max_area and circularity >= cfg.min_circularity and
                    fill >= cfg.min_fill and .65 <= ratio <= 1.55):
                quality = min(1.0, circularity / .9, fill / .98)
                targets.append(Target(float(x), float(y), float(radius), float(area), quality))
                continue
            # Two or more touching cyan discs form one non-circular contour. Distance
            # transform maxima recover their individual centers without a trained model.
            split = self._split_touching(contour, mask, scale)
            if len(split) >= 2:
                targets.extend(split)
                continue
            # A weapon model can cover most of a target. A visible circular arc still
            # gives a useful enclosing-circle estimate, but is marked lower quality so
            # calibration will never select it.
            if (area <= cfg.max_area and circularity >= .35 and fill >= .30 and
                    .42 <= ratio <= 1.7):
                targets.append(Target(float(x), float(y), float(radius), float(area), .45))
        return sorted(targets, key=lambda t: t.distance(frame.center)), mask

    def _split_touching(self, contour, mask, scale=1.0):
        cfg = self.config
        x, y, width, height = cv2.boundingRect(contour)
        if width < 5 or height < 5:
            return []
        blob = np.zeros((height, width), dtype=np.uint8)
        shifted = contour - np.array([[[x, y]]], dtype=contour.dtype)
        cv2.drawContours(blob, [shifted], -1, 255, thickness=-1)
        distance = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
        maximum = float(distance.max())
        if maximum < 2:
            return []
        cores = (distance >= maximum * .60).astype(np.uint8)
        count, labels, stats, centers = cv2.connectedComponentsWithStats(cores, 8)
        result = []
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] < 4:
                continue
            component = np.where(labels == label, distance, 0)
            peak_y, peak_x = np.unravel_index(int(component.argmax()), component.shape)
            radius = float(component[peak_y, peak_x]) / scale
            estimated_area = float(np.pi * radius * radius)
            if not cfg.min_area <= estimated_area <= cfg.max_area:
                continue
            # Weighted core centroid is steadier than an arbitrary maximum on a plateau.
            weights = component[labels == label]
            coords_y, coords_x = np.nonzero(labels == label)
            center_x = (float(np.average(coords_x, weights=weights)) + x) / scale
            center_y = (float(np.average(coords_y, weights=weights)) + y) / scale
            result.append(Target(center_x, center_y, radius, estimated_area, .9))
        return result


def annotate(frame, targets, state, selected=None):
    image = frame.image.copy()
    for target in targets:
        color = (0, 200, 255) if target == selected else ((0, 220, 0) if target.quality >= .8 else (255, 180, 0))
        point = (round(target.x), round(target.y))
        cv2.circle(image, point, round(target.radius), color, 1)
        cv2.drawMarker(image, point, color, cv2.MARKER_CROSS, 8, 1)
    cv2.drawMarker(image, tuple(round(v) for v in frame.center), (255, 255, 255), cv2.MARKER_CROSS, 18, 1)
    cv2.putText(image, state, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1, cv2.LINE_AA)
    return image
