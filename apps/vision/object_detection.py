from pathlib import Path

import cv2
from ultralytics import YOLO

# Load a small pretrained AI object detection model
model = YOLO(str(Path(__file__).resolve().parents[2] / "models/vision/yolo11n.pt"))

# Open MacBook camera
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    raise RuntimeError("Cannot access camera. Check macOS camera permissions.")

print("G1 Smart AI Assistant is running!")
print("Show an object to the camera. Press Q to quit.")

while True:
    success, frame = camera.read()

    if not success:
        print("Could not read camera frame.")
        break

    # Detect objects
    results = model(frame, verbose=False)

    # Draw detected objects and labels
    annotated_frame = results[0].plot()

    cv2.imshow("G1 Smart AI - Object Detection", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()

