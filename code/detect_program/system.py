import cv2
from ultralytics import YOLO
import numpy as np
import time
import requests
import threading
import queue
import base64
import torch


NGROK_URL = ""

detect = YOLO("runs/detect/train10/weights/best.pt").to('cuda' if torch.cuda.is_available() else 'cpu')
detect.fuse()
# segment = YOLO("BATTERY_SEG/runs/segment/train4/weights/best.pt")

# новые
detect_label = YOLO("runs/detect/train15/weights/best.pt").to('cuda' if torch.cuda.is_available() else 'cpu')
# segment_label = YOLO("BATTERY_SEG/runs/segment/train6/weights/best.pt")


frame_width = 1920
margin = 550
roi_x1 = (frame_width // 2) - margin
roi_x2 = (frame_width // 2) + margin


total_batteries = 0
battery_with_label = 0
tracked_ids = set()
jam_ids = set()
best_frames = {}

number_speed = 0
last_speed_time = time.time()

task_queue = queue.Queue()
stop_event = threading.Event()

def get_sharpness(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def is_centered(box, frame_width):
    center_x = (box[0] + box[2]) / 2
    center = frame_width // 2
    return abs(center_x - center) < 50

def async_worker():
    while not stop_event.is_set():
        try:
            task = task_queue.get(timeout=1)
            if task is None:
                continue
                
            if task['type'] == 'update':
                try:
                    requests.post(NGROK_URL + "/update", json=task['data'], timeout=5)
                except Exception as e:
                    print("❌ Ошибка отправки /update:", e)
                    
            elif task['type'] == 'speed':
                try:
                    requests.post(NGROK_URL + "/speed", json=task['data'], timeout=5)
                    print("📡 Отправлено значение скорости:", task['data']['value'])
                except Exception as e:
                    print("❌ Ошибка отправки /speed:", e)
            elif task['type'] == 'jam':
                try:
                    requests.post(NGROK_URL + "/jam", json=task['data'], timeout=12)
                    print(f"📨 Jam notification sent")
                except Exception as e:
                    print(f"❌ Ошибка отправки /jam: {e}")
            elif task['type'] == 'defect':
                try:
                    requests.post(NGROK_URL + "/defect", json=task['data'], timeout=12)
                    print(f"📨 Defect notification sent")
                except Exception as e:
                    print(f"❌ Ошибка отправки /defect: {e}")
                
        except queue.Empty:
            continue
        except Exception as e:
            print("Ошибка в worker:", e)

def process_battery(full_frame, box, battery_id):
    global battery_with_label

    x1, y1, x2, y2 = box
    cropped = full_frame[y1:y2, x1:x2]

    results = detect_label(cropped, conf=0.7, verbose=False)[0]

    has_label = results.boxes is not None and len(results.boxes) > 0

    if has_label:
        battery_with_label += 1
        return 1
    else:
        print(f"🚨 БЕЗ ЭТИКЕТКИ: ID {battery_id}")

        timestamp = time.strftime("%H:%M:%S")
        ret, buffer = cv2.imencode('.jpg', cropped)


        img_b64 = base64.b64encode(buffer.tobytes()).decode('ascii')

        task_queue.put({
            'type': 'defect',
            'data': {
                'timestamp': timestamp,
                'type_defect': 'отсутсвует этикетка',
                'camera_id': 'camera_1',
                'image_b64': img_b64,
            }
        })

        return 0


def run_system():
    global total_batteries, battery_with_label, tracked_ids, best_frames, number_speed, last_speed_time

    worker_thread = threading.Thread(target=async_worker, daemon=True)
    worker_thread.start()

    cap = cv2.VideoCapture("video/extra.mp4", cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        
    frame_index = 0
    frame_skip_rate = 7

    NormalMode = True

    last_detection_time = time.time()
    previous_sleep_frame = None

    sleep_roi_width = 150
    sleep_threshold = 11
    battery_times = 0
    id_last = -1

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            current_time = time.time()

            if (NormalMode):
                roi = frame[:, roi_x1:roi_x2]
                results = detect.track(roi, batch=4, iou=0.5, conf=0.7, persist=True, imgsz=608, tracker="bytetrack.yaml", verbose=False)

                if results[0].boxes.id is not None:
                    boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                    ids = results[0].boxes.id.cpu().numpy().astype(int)

                    for box, id in zip(boxes, ids):
                        box[0] += roi_x1
                        box[2] += roi_x1

                        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), (0, 255, 0), 2)
                        cv2.putText(frame, f"ID {id}", (box[0], box[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

                        now = time.time()
                        if id != id_last:
                            battery_times = now
                            id_last = id
                        elif now - battery_times > 7 and id not in jam_ids:
                            print(f"🚨 Затор: ID {id}")

                            timestamp = time.strftime("%H:%M:%S")
                            ret, buffer = cv2.imencode('.jpg', frame)
                            img_b64 = base64.b64encode(buffer.tobytes()).decode('ascii')

                            task_queue.put({
                                'type': 'jam',
                                'data': {
                                    'timestamp': timestamp,
                                    'camera_id': 'camera_1',
                                    'image_b64': img_b64,
                                }
                            })
                            jam_ids.add(id)

                        if is_centered(box, frame_width):
                            sharpness = get_sharpness(frame[box[1]:box[3], box[0]:box[2]])
                            if id not in best_frames or sharpness > best_frames[id]['sharpness']:
                                best_frames[id] = {'frame': frame.copy(), 'box': box.copy(), 'sharpness': sharpness}
                            

                        center_x = (box[0] + box[2]) / 2
                        if center_x < (frame_width / 2) - 50 and id not in tracked_ids:
                            if id in best_frames:
                                best_data = best_frames[id]
                                haslabel = process_battery(best_data['frame'], best_data['box'], id)
                                total_batteries += 1
                                number_speed += 1
                                tracked_ids.add(id)

                                task_queue.put({
                                    'type': 'update',
                                    'data': {
                                        'count': 1,
                                        'with_label': haslabel
                                    }
                                })
                                best_frames.pop(id, None)

                    last_detection_time = current_time
     

                if current_time - last_detection_time > 7:
                    print("⚡ Переход в энергосберегающий режим")
                    NormalMode = False

            else:
                if frame_index % frame_skip_rate == 0:
                    sleep_roi = frame[:, -sleep_roi_width:]

                    if previous_sleep_frame is not None:
                        diff = cv2.absdiff(sleep_roi, previous_sleep_frame)
                        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                        mean_diff = np.mean(gray)

                        if mean_diff > sleep_threshold:
                            print("🚀 Обнаружено движение, возвращаемся в обычный режим")
                            NormalMode = True
                            last_detection_time = current_time

                    previous_sleep_frame = sleep_roi.copy()
                
                frame_index += 1


            if time.time() - last_speed_time >= 60:
                task_queue.put({
                    'type': 'speed',
                    'data': {'value': number_speed}
                })
                number_speed = 0
                last_speed_time = time.time()

            # frame = cv2.resize(frame, (0, 0), fx=0.75, fy=0.75)
            # cv2.imshow("Frame", frame)
            if cv2.waitKey(1) == ord("q"):
                break

    finally:
        stop_event.set()
        worker_thread.join()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run_system()
